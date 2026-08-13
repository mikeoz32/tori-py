from tori_py_persistent_streams_core import StartModeCapabilities

RABBITMQ_START_MODE_CAPABILITIES = StartModeCapabilities(
    beginning=True,
    end=True,
    exact_offset=True,
    timestamp=False,
    relative_time=False,
)
