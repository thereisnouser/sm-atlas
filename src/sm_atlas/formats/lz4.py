from __future__ import annotations


class Lz4BlockError(ValueError):
    """Raised when a raw LZ4 block cannot be decoded."""


def decompress_block(
    data: bytes,
    *,
    max_output_size: int = 1024 * 1024,
) -> bytes:
    """Decode a raw LZ4 block without a frame header."""
    source_index = 0
    output = bytearray()

    while source_index < len(data):
        token = data[source_index]
        source_index += 1

        literal_length = token >> 4
        if literal_length == 15:
            while True:
                if source_index >= len(data):
                    raise Lz4BlockError("truncated literal length")

                extra = data[source_index]
                source_index += 1
                literal_length += extra

                if extra != 255:
                    break

        literal_end = source_index + literal_length
        if literal_end > len(data):
            raise Lz4BlockError("truncated literal data")

        if len(output) + literal_length > max_output_size:
            raise Lz4BlockError("decompressed block is too large")

        output.extend(data[source_index:literal_end])
        source_index = literal_end

        if source_index == len(data):
            break

        if source_index + 2 > len(data):
            raise Lz4BlockError("truncated match offset")

        offset = (
            data[source_index]
            | (data[source_index + 1] << 8)
        )
        source_index += 2

        if offset == 0 or offset > len(output):
            raise Lz4BlockError("invalid match offset")

        match_length = token & 0x0F
        if match_length == 15:
            while True:
                if source_index >= len(data):
                    raise Lz4BlockError("truncated match length")

                extra = data[source_index]
                source_index += 1
                match_length += extra

                if extra != 255:
                    break

        match_length += 4

        if len(output) + match_length > max_output_size:
            raise Lz4BlockError("decompressed block is too large")

        match_start = len(output) - offset
        for index in range(match_length):
            output.append(output[match_start + index])

    return bytes(output)
