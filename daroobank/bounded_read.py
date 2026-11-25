"""Bounded reads from blocking binary streams; not a timeout or network sandbox."""

READ_CHUNK_BYTES = 64 * 1024
MAX_READ_CALLS = 8192


def read_bounded_bytes(stream, *, limit):
    """Read to EOF or one byte beyond limit, tolerating ordinary short reads.

    Empty bytes mean EOF. A nonblocking or misbehaving stream is rejected,
    rather than silently treating an incomplete read as a complete file.
    The call cap prevents a stream returning a byte forever from looping forever.
    """
    if type(limit) is not int or limit < 0:
        raise ValueError('A nonnegative integer limit is required')
    chunks = []
    total = 0
    for _ in range(MAX_READ_CALLS):
        requested = min(READ_CHUNK_BYTES, limit + 1 - total)
        try:
            chunk = stream.read(requested)
        except ValueError as exc:  # e.g. a closed binary file
            raise OSError('Binary stream is not readable') from exc
        if not isinstance(chunk, (bytes, bytearray)) or len(chunk) > requested:
            raise OSError('Binary stream did not honor the bounded read')
        if not chunk:
            return b''.join(chunks)
        chunks.append(bytes(chunk))
        total += len(chunk)
        if total > limit:
            return b''.join(chunks)
    raise OSError('Binary stream did not reach EOF within the read-call limit')
