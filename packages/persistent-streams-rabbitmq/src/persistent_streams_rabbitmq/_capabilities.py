from persistent_streams import StartModeCapabilities

RABBITMQ_START_MODE_CAPABILITIES = StartModeCapabilities(
    beginning=True,
    end=True,
    exact_offset=True,
    timestamp=False,
    relative_time=False,
)
