import asyncio
import logging
import os
import time
from datetime import datetime

import backoff
import orjson
from azure.eventhub import EventData, PartitionContext, TransportType
from azure.eventhub.aio import EventHubConsumerClient
from azure.eventhub.exceptions import EventHubError
from azure.eventhub.extensions.checkpointstoreblobaio import BlobCheckpointStore
from dotenv import load_dotenv
from flatdict import FlatDict
from pythonjsonlogger import jsonlogger

from microsoft_azure_eventhub_source._CleanEvent import CleanEvent

try:
    from syslogng import LogMessage, LogSource

    syslogng = True
except ImportError:
    syslogng = False

    class LogSource:
        pass

    class LogMessage:
        pass


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)
        if not log_record.get("timestamp"):
            # this doesn't use record.created, so it is slightly off
            now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            log_record["timestamp"] = now
        if log_record.get("level"):
            log_record["level"] = log_record["level"].upper()
        else:
            log_record["level"] = record.levelname

        log_record["threadName"] = record.threadName
        log_record["lineno"] = record.lineno
        log_record["module"] = record.module
        log_record["exc_info"] = record.exc_info
        log_record["exc_text"] = record.exc_text


# logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)

logHandler = logging.StreamHandler()
formatter = CustomJsonFormatter()
logHandler.setFormatter(formatter)

logger.addHandler(logHandler)

load_dotenv()


def _backoff_handler(details):
    logger.warning(
        "Backing off {wait:0.1f} seconds after {tries} tries "
        "calling function {target} with args {args} and kwargs "
        "{kwargs}".format(**details)
    )


AZURE_STORAGE_CONN_STR: str = os.environ["AZURE_STORAGE_CONN_STR"]
AZURE_STORAGE_CONTAINER: str = os.environ["AZURE_STORAGE_CONTAINER"]
EVENT_HUB_CONN_STR: str = os.environ["EVENT_HUB_CONN_STR"]
# EVENT_HUB_NAME = os.environ['EVENT_HUB_NAME']
EVENT_HUB_CONSUMER_GROUP: str = os.environ["EVENT_HUB_CONSUMER_GROUP"]
EVENT_HUB_TRANSPORT_TYPE: str = os.environ.get(
    "EVENT_HUB_TRANSPORT_TYPE", "default"
).upper()
EVENT_HUB_STARTING_POSITION: str = os.environ.get(
    "EVENT_HUB_STARTING_POSITION", "-1"
).upper()

transportType = TransportType.Amqp
if EVENT_HUB_TRANSPORT_TYPE == "AmqpOverWebsocket".upper():
    transportType = TransportType.AmqpOverWebsocket


class LogSourcePlugin(LogSource):
    """Provides a syslog-ng async source for Mimecast"""

    _cancelled: bool = False
    _partition_last_checkpoint_time = dict()
    _checkpoint_time_interval = 30

    def init(self, options):
        """Syslog NG doesn't use the python init so any one time setup is done here"""

        # logger.trace(options)
        logger.info(AZURE_STORAGE_CONN_STR)
        logger.info(AZURE_STORAGE_CONTAINER)
        logger.info(EVENT_HUB_CONN_STR)
        logger.info(EVENT_HUB_CONSUMER_GROUP)

        return True

    def run(self):
        """Called by Syslog-ng to start the function"""

        logger.info("Run called by syslog-ng")
        asyncio.run(self.run_async())

    def request_exit(self):
        """Called by syslog NG on exit"""

        logger.info("Exit called by syslog-ng")
        self._cancelled = True

    @backoff.on_exception(backoff.expo, EventHubError)
    async def run_async(self):
        """Actual start of process"""

        checkpoint_store: BlobCheckpointStore = (
            BlobCheckpointStore.from_connection_string(
                AZURE_STORAGE_CONN_STR, AZURE_STORAGE_CONTAINER
            )
        )
        logger.info("Checkpoint connected")
        client: EventHubConsumerClient = EventHubConsumerClient.from_connection_string(
            EVENT_HUB_CONN_STR,
            consumer_group=EVENT_HUB_CONSUMER_GROUP,
            checkpoint_store=checkpoint_store,
            transport_type=transportType,
            check_case=True,
        )
        logger.info("client connected")
        async with client:
            logger.info("waiting on batch")
            await client.receive_batch(
                on_event_batch=self.on_event_batch,
                max_wait_time=1,
                starting_position="-1",  # "-1" is from the beginning of the partition.
                max_batch_size=300,
                prefetch=1000,
                track_last_enqueued_event_properties=True,
            )

    async def on_event_batch(
        self, partition_context: PartitionContext, event_batch: EventData
    ):
        """Accept call from api with batch"""
        logger.info(
            f"ehs: Partition {partition_context.partition_id}, Received count: {len(event_batch)}"
        )
        try:
            for event in event_batch:
                event_obj = event.body_as_json()
                logger.info(f'ehs: Record count {len(event_obj["records"])}')
                if "records" in event_obj:
                    for record in event_obj["records"]:
                        CleanEvent(record)
                        message = orjson.dumps(record)
                        if syslogng:
                            single_event = LogMessage(message)
                            if "time" in record:
                                event_time = datetime.fromisoformat(record["time"])
                            else:
                                event_time = event.enqueued_time
                            single_event.set_timestamp(event_time)
                            single_event[
                                ".internal.enqueued_time"
                            ] = event.enqueued_time.isoformat()
                            for field_key, field_value in FlatDict(
                                record, delimiter="."
                            ).items():
                                if field_key not in ("time"):
                                    try:
                                        single_event[f".Vendor.{field_key}"] = str(
                                            field_value
                                        )
                                    except ValueError:
                                        logger.error(
                                            f"ValueError: {field_key}={field_value} - {message}"
                                        )
                            self.post_message(single_event)
                        else:
                            logger.debug(record)
                else:
                    CleanEvent(event_obj)
                    message = orjson.dumps(event_obj)
                    if syslogng:
                        record_lmsg = LogMessage(message)
                        self.post_message(record_lmsg)
                    else:
                        logger.debug(event_obj)
                p_id = partition_context.partition_id
                now_time = time.time()
                last_checkpoint_time = self._partition_last_checkpoint_time.get(p_id)
                if (
                    last_checkpoint_time is None
                    or (now_time - last_checkpoint_time)
                    >= self._checkpoint_time_interval
                ):
                    await partition_context.update_checkpoint(event)
                    self._partition_last_checkpoint_time[p_id] = now_time

        except Exception as argument:
            logger.exception(argument)


def main():
    source = LogSourcePlugin()
    source.init({})
    source.run()


if __name__ == "__main__":
    main()
