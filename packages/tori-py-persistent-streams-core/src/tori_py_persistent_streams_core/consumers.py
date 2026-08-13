from __future__ import annotations

import asyncio

from tori_py_persistent_streams_core.errors import (
    CheckpointPersistenceError,
    OwnershipError,
    PoisonRecordError,
)
from tori_py_persistent_streams_core.models import ResumeCursor
from tori_py_persistent_streams_core.protocols import PartitionLease, RecordHandler


class ConsumerRunner:
    """Runs a finite serial processing pull for one owned partition."""

    async def run_once(
        self,
        lease: PartitionLease,
        handler: RecordHandler,
        *,
        limit: int = 1,
    ) -> int:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        processed = 0
        try:
            while processed < limit:
                record = await lease.next_record()
                if record is None:
                    return processed
                try:
                    await handler(record)
                except Exception as error:
                    await _stop_ignoring_errors(lease)
                    raise PoisonRecordError(
                        lease.key.stream,
                        lease.key.group,
                        lease.key.partition,
                        record.offset,
                        record.record_id,
                        error,
                    ) from error
                try:
                    await lease.checkpoint(record)
                except Exception as error:
                    await _stop_ignoring_errors(lease)
                    if isinstance(error, (CheckpointPersistenceError, OwnershipError)):
                        raise
                    raise CheckpointPersistenceError(
                        cursor=ResumeCursor.last_successful(record.offset), cause=error
                    ) from error
                processed += 1
            return processed
        except asyncio.CancelledError:
            await _release_preserving_cancellation(lease)
            raise
        except KeyboardInterrupt, SystemExit:
            try:
                await lease.release()
            except BaseException:
                pass
            raise


async def _release_preserving_cancellation(lease: PartitionLease) -> None:
    task = asyncio.create_task(lease.release())
    try:
        await asyncio.shield(task)
    except BaseException:
        if not task.done():
            task.cancel()


async def _stop_ignoring_errors(lease: PartitionLease) -> None:
    try:
        await lease.stop()
    except BaseException:
        pass
