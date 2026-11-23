"""Boundary and failure semantics of the blocking binary read helper."""
import io
from unittest.mock import patch

from django.test import SimpleTestCase

from .bounded_read import read_bounded_bytes


class Chunks:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.requested = []

    def read(self, size):
        self.requested.append(size)
        return next(self.chunks)


class BoundedReadTests(SimpleTestCase):
    def test_short_reads_and_utf8_boundary_are_preserved(self):
        data = 'آزمون'.encode('utf-8')
        stream = Chunks([data[:1], data[1:5], bytearray(data[5:]), b''])
        self.assertEqual(read_bounded_bytes(stream, limit=100), data)
        self.assertEqual(len(stream.requested), 4)

    def test_exact_limit_eof_and_one_extra_byte(self):
        for data, limit in [(b'', 0), (b'abcd', 4), (b'abcde', 4), (b'x', 0)]:
            with self.subTest(data=data, limit=limit):
                self.assertEqual(read_bounded_bytes(io.BytesIO(data), limit=limit), data)
        stream = io.BytesIO(b'abcdef')
        self.assertEqual(read_bounded_bytes(stream, limit=4), b'abcde')
        self.assertEqual(stream.tell(), 5)

    def test_unusable_or_nonbinary_stream_is_not_eof(self):
        for chunks in ([None], ['text'], [b'ok', None], [b'oversized']):
            with self.subTest(chunks=chunks), self.assertRaises(OSError):
                read_bounded_bytes(Chunks(chunks), limit=3)
        closed = io.BytesIO(b'test')
        closed.close()
        with self.assertRaises(OSError):
            read_bounded_bytes(closed, limit=4)

    def test_failed_read_is_propagated_and_call_cap_fails_closed(self):
        class OneByteForever:
            def read(self, size):
                return b'x'
        with patch('daroobank.bounded_read.MAX_READ_CALLS', 3), self.assertRaises(OSError):
            read_bounded_bytes(OneByteForever(), limit=10)
        stream = Chunks([b'ok'])
        def fail(_size):
            raise OSError('synthetic read failure')
        stream.read = fail
        with self.assertRaisesRegex(OSError, 'synthetic read failure'):
            read_bounded_bytes(stream, limit=10)

    def test_limit_validation(self):
        for limit in [-1, True, 1.5, '1']:
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                read_bounded_bytes(io.BytesIO(b''), limit=limit)
