try:
    from syslogng import register_config_generator
except ImportError:
    pass

from importlib import resources as impresources
from logging import StreamHandler, getLogger

from pythonjsonlogger import jsonlogger

from microsoft_azure_eventhub_source import conf

logger = getLogger(__name__)

logHandler = StreamHandler()
formatter = jsonlogger.JsonFormatter()
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)


def _plugin_config_generator(args):
    inp_file = impresources.files(conf) / "source.conf"
    logger.error(f"Source {inp_file}")
    with inp_file.open("rt") as f:
        return f.read() + "\n"


def register_plugin_config_generator():
    register_config_generator(
        context="root",
        name="microsoft_azure_eventhub_source",
        config_generator=_plugin_config_generator,
    )


def main():
    print(_plugin_config_generator({}))


if __name__ == "__main__":
    main()
