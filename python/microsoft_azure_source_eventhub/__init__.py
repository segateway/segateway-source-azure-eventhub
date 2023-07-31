import orjson
import time
from syslogng import LogSource
from syslogng import LogMessage
from syslogng import Logger
import asyncio

import os
from azure.eventhub import PartitionContext, EventData, TransportType
from azure.eventhub.aio import EventHubConsumerClient
from azure.eventhub.extensions.checkpointstoreblobaio import (
    BlobCheckpointStore,
)
from flatten_dict import flatten

logger = Logger()

AZURE_STORAGE_CONN_STR: str = os.environ["AZURE_STORAGE_CONN_STR"]
AZURE_STORAGE_CONTAINER: str = os.environ["AZURE_STORAGE_CONTAINER"]
EVENT_HUB_CONN_STR: str = os.environ["EVENT_HUB_CONN_STR"]
# EVENT_HUB_NAME = os.environ['EVENT_HUB_NAME']
EVENT_HUB_CONSUMER_GROUP: str = os.environ["EVENT_HUB_CONSUMER_GROUP"]
EVENT_HUB_TRANSPORT_TYPE: str = os.environ.get("EVENT_HUB_TRANSPORT_TYPE","default").upper()

transportType = TransportType.Amqp
if EVENT_HUB_TRANSPORT_TYPE == "AmqpOverWebsocket".upper():
    transportType =  TransportType.AmqpOverWebsocket
    
    
class MicrosoftEventHubSource(LogSource):
    """Provides a syslog-ng async source for Microsoft Event hub"""

    cancelled: bool = False

    def init(self, options):
        """Class init with options"""

        # logger.trace(options)
        logger.trace(AZURE_STORAGE_CONN_STR)
        logger.trace(AZURE_STORAGE_CONTAINER)
        logger.trace(EVENT_HUB_CONN_STR)
        logger.trace(EVENT_HUB_CONSUMER_GROUP)
        return True

    def run(self):
        """Simple Run method to create the loop"""
        asyncio.run(self.receive_batch())

    # async def main(self):
    #     '''This is a main'''
    #     await asyncio.gather(self.receive_batch())

    async def receive_batch(self):
        """Do the work"""
        checkpoint_store: BlobCheckpointStore = (
            BlobCheckpointStore.from_connection_string(
                AZURE_STORAGE_CONN_STR, AZURE_STORAGE_CONTAINER
            )
        )
        client: EventHubConsumerClient = EventHubConsumerClient.from_connection_string(
            EVENT_HUB_CONN_STR,
            consumer_group=EVENT_HUB_CONSUMER_GROUP,
            checkpoint_store=checkpoint_store,
            transport_type=transportType,           
            check_case=True,
        )
        async with client:
            while not self.cancelled:
                await client.receive_batch(
                    on_event_batch=self.on_event_batch,
                    max_batch_size=200,
                    prefetch=500,
                    max_wait_time=10,
                    starting_position="-1",  # "-1" is from the beginning of the partition.
                    track_last_enqueued_event_properties=True,
                )
            logger.info("ehs: run will sleep")
            await asyncio.sleep(1)

    def request_exit(self):
        """Called by syslog NG on exit"""
        self.cancelled = True

    async def batch_process_events(self, event_batch: EventData):
        """Process one batch"""
        # put your code here
        try:
            for event in event_batch:
                event_str = event.body_as_str(encoding="UTF-8")
                event_obj = orjson.loads(event_str)
                logger.debug(f'ehs: Record count {len(event_obj["records"])}')            
                if "records" in event_obj:
                    for record in event_obj["records"]:

                        MicrosoftEventHubSource.clean_event(record)
                        message = orjson.dumps(record)

                        record_lmsg = LogMessage(message)
                        record_lmsg[".internal.enqueued_time"] = event.enqueued_time.isoformat()

                        self.post_message(record_lmsg)
                else:
                    MicrosoftEventHubSource.clean_event(event_obj)
                    message = orjson.dumps(event_obj)
                    record_lmsg = LogMessage(message)
                    self.post_message(record_lmsg)
        except Exception as argument:            
            logger.error(argument)


    async def on_event_batch(
        self, partition_context: PartitionContext, event_batch: EventData
    ):
        """Accept call from api with batch"""
        logger.debug(
            f"ehs: Partition {partition_context.partition_id}, Received count: {len(event_batch)}"
        )
        if len(event_batch) > 0:
            await self.batch_process_events(event_batch)
            await partition_context.update_checkpoint()

    @staticmethod
    def clean_event(source_dict: dict):
        """
        Delete keys with the value ``None``  or ```` (empty) string in a dictionary, recursively.
        Remove empty list and dict objects

        This alters the input so you may wish to ``copy`` the dict first.
        """
        # For Python 3, write `list(d.items())`; `d.items()` won’t work
        # For Python 2, write `d.items()`; `d.iteritems()` won’t work
        for key, value in list(source_dict.items()):
            if value is None:
                del source_dict[key]
            elif isinstance(value, str) and value in ("", "None", "none"):
                del source_dict[key]
            elif isinstance(value, str):
                if value.endswith("\n"):
                    value = value.strip("\n")

                if value.startswith('{"'):
                    try:
                        value = orjson.loads(value)
                        MicrosoftEventHubSource.clean_event(value)
                        source_dict[key] = value
                    except orjson.JSONDecodeError:
                        pass
            elif isinstance(value, dict) and not value:
                del source_dict[key]
            elif isinstance(value, dict):
                MicrosoftEventHubSource.clean_event(value)
            elif isinstance(value, list) and not value:
                del source_dict[key]
        return source_dict  # For convenience