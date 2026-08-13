from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Annotated, ClassVar, Protocol, cast
from uuid import UUID

from tori_py import (
    ArgumentMetadata,
    Inject,
    NestApplication,
    controller,
    injectable,
    module,
    use_pipe,
)
from tori_py_persistent_streams import (
    ConfiguredStreamPublisher,
    PersistentStreamsModule,
    PersistentStreamsOptions,
    PersistentStreamsRuntimeOptions,
    PublisherRegistration,
    StreamOffset,
    StreamPartition,
    StreamPayload,
    StreamPublisher,
    stream_handler,
    stream_publish,
    stream_publisher_token,
)
from tori_py_persistent_streams.options import StreamBinding
from tori_py_persistent_streams.testing import InMemoryPersistentStreamsModule
from tori_py_persistent_streams_core import PublishReceipt, StreamDefinition

STREAM_ALIAS = "member-activity"
NAMED_PUBLISHER = "member-updates"
STREAM_DEFINITION = StreamDefinition("member-activity-v1", partition_count=2)


@dataclass(frozen=True)
class MemberUpdated:
    member_id: str
    display_name: str


class MemberUpdatedCodec:
    def encode(self, payload: MemberUpdated) -> bytes:
        return json.dumps(
            {"member_id": payload.member_id, "display_name": payload.display_name},
            separators=(",", ":"),
        ).encode()

    def decode(self, payload: bytes, target: type[MemberUpdated]) -> MemberUpdated:
        del target
        value = json.loads(payload)
        return MemberUpdated(value["member_id"], value["display_name"])


class MemberPartitionKey:
    def resolve(self, payload: MemberUpdated) -> bytes:
        return payload.member_id.encode()


class MemberActivityPublisher(Protocol):
    @stream_publish(payload=MemberUpdated)
    async def member_updated(
        self,
        payload: MemberUpdated,
        *,
        record_id: UUID | None = None,
    ) -> PublishReceipt: ...


class NormalizeDisplayName:
    async def transform(self, value: object, metadata: ArgumentMetadata) -> object:
        if metadata.binding_kind != "payload":
            return value
        value = cast(MemberUpdated, value)
        return MemberUpdated(value.member_id, value.display_name.strip().title())


@dataclass(frozen=True)
class HandledMemberUpdate:
    payload: MemberUpdated
    partition: int
    offset: int


@controller()
class MemberProjection:
    handled: ClassVar[list[HandledMemberUpdate]] = []

    @stream_handler(stream=STREAM_ALIAS, consumer_group="member-card-v1")
    @use_pipe(NormalizeDisplayName())
    async def apply(
        self,
        payload: Annotated[MemberUpdated, StreamPayload()],
        partition: Annotated[int, StreamPartition()],
        offset: Annotated[int, StreamOffset()],
    ) -> None:
        MemberProjection.handled.append(HandledMemberUpdate(payload, partition, offset))


@injectable()
class DemoRunner:
    receipts: ClassVar[list[PublishReceipt]] = []

    def __init__(
        self,
        raw: StreamPublisher,
        named: Annotated[
            ConfiguredStreamPublisher[MemberUpdated],
            Inject(stream_publisher_token(NAMED_PUBLISHER)),
        ],
        protocol: MemberActivityPublisher,
    ) -> None:
        self._raw = raw
        self._named = named
        self._protocol = protocol

    async def on_application_bootstrap(self) -> None:
        DemoRunner.receipts = [
            await self._raw.publish(
                STREAM_ALIAS, MemberUpdated("member-1", "  ada lovelace ")
            ),
            await self._named.publish(MemberUpdated("member-6", "  grace hopper ")),
            await self._protocol.member_updated(
                MemberUpdated("member-3", "  alan turing ")
            ),
        ]

        async with asyncio.timeout(1):
            while len(MemberProjection.handled) < len(DemoRunner.receipts):
                await asyncio.sleep(0.005)


binding = StreamBinding[MemberUpdated](
    alias=STREAM_ALIAS,
    definition=STREAM_DEFINITION,
    payload_type=MemberUpdated,
    codec=MemberUpdatedCodec(),
    partition_key_resolver=MemberPartitionKey(),
)

options = PersistentStreamsOptions(
    bindings=(binding,),
    publishers=(
        PublisherRegistration(
            STREAM_ALIAS,
            name=NAMED_PUBLISHER,
            protocol=MemberActivityPublisher,
        ),
    ),
    runtime=PersistentStreamsRuntimeOptions(poll_interval=0.001),
)


def application_module() -> type[object]:
    # Each application owns a fresh adapter because shutdown permanently closes it.
    streams = PersistentStreamsModule.for_root(
        options,
        imports=[InMemoryPersistentStreamsModule.for_root()],
    )

    @module(
        imports=[streams],
        controllers=[MemberProjection],
        providers=[DemoRunner],
    )
    class ApplicationModule:
        pass

    return ApplicationModule


async def create_application() -> NestApplication:
    MemberProjection.handled.clear()
    DemoRunner.receipts.clear()
    return await NestApplication.create(application_module())


async def main() -> None:
    application = await create_application()
    try:
        await application.start()
        for handled in MemberProjection.handled:
            print(handled)
    finally:
        await application.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
