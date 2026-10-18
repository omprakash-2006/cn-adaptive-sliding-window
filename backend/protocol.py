"""
protocol.py - Networking Protocol Layer
========================================
This module implements fundamental Computer Networks (CN) concepts:
1. Framing: Custom binary header with Magic bytes, Sequence Number, Type, Length, Checksum, and Hamming ECC.
   Solves TCP byte-stream delimitation and fragmentation.
2. Error Detection: CRC-32 checksum to verify payload integrity.
3. Error Correction: Hamming(7, 4) Code for forward error correction (FEC) on critical status bytes.
4. ARQ Retransmission: NACK-driven automatic retransmission for uncorrectable corrupted frames.
5. Transmission Error Simulation: Controlled bit-flipping to demonstrate error detection & correction.
"""

import struct
import binascii
import random
import time

# --- FRAME TYPE CONSTANTS ---
TYPE_REQUEST = 1       # Client querying student result
TYPE_QUEUE_UPDATE = 2  # Server informing client of live queue position
TYPE_RESULT_DATA = 3   # Server sending student result record
TYPE_ERROR_NACK = 4    # Receiver reporting corrupted frame (ARQ request)
TYPE_ACK = 5           # Positive acknowledgement
TYPE_RELEASE_INFO = 6  # Published exam/version/hash expected for this request
TYPE_STALE_NACK = 7    # CRC-valid data is outdated or inconsistent
TYPE_VERSION_CHECK = 8  # Ask whether the received version is still current
TYPE_VERSION_ACK = 9   # Current at the server's serialized verification decision
TYPE_PROTOCOL_ERROR = 10

# Magic Bytes to identify frame boundary (2 bytes: 0xAA, 0x55)
MAGIC_BYTES = b'\xAA\x55'

# Header format:
# MAGIC (2 bytes) + SEQ_NO (4 bytes uint) + FRAME_TYPE (1 byte uchar) +
# DATA_LEN (4 bytes uint) + CHECKSUM (4 bytes uint) + HAMMING_ECC (2 bytes)
# Total header length = 2 + 4 + 1 + 4 + 4 + 2 = 17 bytes
HEADER_FORMAT = '>2sIBII2s'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


def calculate_crc32(data: bytes) -> int:
    """
    Computes a 32-bit Cyclic Redundancy Check (CRC-32) checksum.
    CRC is an error-detecting code commonly used in digital networks (Ethernet, Wi-Fi).
    """
    return binascii.crc32(data) & 0xFFFFFFFF


# ============================================================================
# HAMMING (7, 4) ERROR CORRECTION CODE
# ============================================================================
# Encodes a 4-bit nibble into a 7-bit Hamming codeword with 3 parity bits.
# Can detect and correct any single-bit transmission error.

def hamming_encode_nibble(d: int) -> int:
    """Encodes a 4-bit nibble (0-15) into a 7-bit Hamming codeword."""
    d1 = (d >> 3) & 1
    d2 = (d >> 2) & 1
    d3 = (d >> 1) & 1
    d4 = d & 1

    p1 = d1 ^ d2 ^ d4
    p2 = d1 ^ d3 ^ d4
    p3 = d2 ^ d3 ^ d4

    return (p1 << 6) | (p2 << 5) | (d1 << 4) | (p3 << 3) | (d2 << 2) | (d3 << 1) | d4


def hamming_decode_nibble(c: int) -> tuple[int, bool, int]:
    """
    Decodes a 7-bit codeword.
    Detects and corrects single-bit errors.
    Returns: (decoded_nibble, was_error_corrected, error_bit_position)
    """
    p1 = (c >> 6) & 1
    p2 = (c >> 5) & 1
    d1 = (c >> 4) & 1
    p3 = (c >> 3) & 1
    d2 = (c >> 2) & 1
    d3 = (c >> 1) & 1
    d4 = c & 1

    s1 = p1 ^ d1 ^ d2 ^ d4
    s2 = p2 ^ d1 ^ d3 ^ d4
    s3 = p3 ^ d2 ^ d3 ^ d4

    error_pos = (s3 << 2) | (s2 << 1) | s1
    corrected = False

    if error_pos != 0:
        corrected = True
        c ^= (1 << (7 - error_pos))
        d1 = (c >> 4) & 1
        d2 = (c >> 2) & 1
        d3 = (c >> 1) & 1
        d4 = c & 1

    decoded_nibble = (d1 << 3) | (d2 << 2) | (d3 << 1) | d4
    return decoded_nibble, corrected, error_pos


def encode_status_with_hamming(status_byte: int) -> bytes:
    """
    Encodes an 8-bit status code into two 7-bit Hamming codewords (stored in 2 bytes).
    Demonstrates FEC (Forward Error Correction) on critical control bytes.
    """
    high_nibble = (status_byte >> 4) & 0x0F
    low_nibble = status_byte & 0x0F
    c_high = hamming_encode_nibble(high_nibble)
    c_low = hamming_encode_nibble(low_nibble)
    return bytes([c_high, c_low])


def decode_status_with_hamming(encoded_bytes: bytes) -> tuple[int, bool, int]:
    """
    Decodes two 7-bit Hamming codewords back into an 8-bit status byte.
    Corrects single-bit errors in either nibble.
    Returns: (status_byte, was_corrected, bit_position)
    """
    if len(encoded_bytes) < 2:
        return 0, False, 0

    c_high = encoded_bytes[0]
    c_low = encoded_bytes[1]

    high_nibble, corr1, pos1 = hamming_decode_nibble(c_high)
    low_nibble, corr2, pos2 = hamming_decode_nibble(c_low)

    status_byte = (high_nibble << 4) | low_nibble
    was_corrected = corr1 or corr2
    err_pos = pos1 if corr1 else pos2
    return status_byte, was_corrected, err_pos


# ============================================================================
# FRAMING UTILITIES
# ============================================================================

def create_frame(
    seq_no: int,
    frame_type: int,
    payload: str or bytes,
    ecc_bytes: bytes = b'\x00\x00',
    override_checksum: int = None
) -> bytes:
    """
    Encapsulates payload into a network frame with a structured binary header:
    [ MAGIC (2B) | SEQ_NO (4B) | TYPE (1B) | DATA_LEN (4B) | CHECKSUM (4B) | ECC (2B) | PAYLOAD ]
    """
    if isinstance(payload, str):
        payload_bytes = payload.encode('utf-8')
    else:
        payload_bytes = payload

    checksum = override_checksum if override_checksum is not None else calculate_crc32(payload_bytes)
    data_len = len(payload_bytes)

    if len(ecc_bytes) != 2:
        ecc_bytes = b'\x00\x00'

    header = struct.pack(HEADER_FORMAT, MAGIC_BYTES, seq_no, frame_type, data_len, checksum, ecc_bytes)
    return header + payload_bytes


def read_exact(sock, n: int) -> bytes or None:
    """
    Reads exactly n bytes from a TCP stream socket.
    Handles TCP byte-stream fragmentation.
    """
    buffer = bytearray()
    while len(buffer) < n:
        try:
            chunk = sock.recv(n - len(buffer))
            if not chunk:
                return None  # Connection closed
            buffer.extend(chunk)
        except (ConnectionResetError, TimeoutError, OSError):
            return None
    return bytes(buffer)


def receive_frame(sock) -> tuple[int, int, bytes, int, bytes, bool] or None:
    """
    Reads a framed message from the socket:
    1. Reads the 17-byte header.
    2. Validates the Magic Bytes to ensure frame synchronization.
    3. Reads the exact payload specified in DATA_LEN.
    4. Computes CRC-32 on received payload to verify data integrity.

    Returns:
        (seq_no, frame_type, payload_bytes, checksum, ecc_bytes, is_valid) or None if closed
    """
    header_bytes = read_exact(sock, HEADER_SIZE)
    if not header_bytes:
        return None

    magic, seq_no, frame_type, data_len, received_checksum, ecc_bytes = struct.unpack(HEADER_FORMAT, header_bytes)

    if magic != MAGIC_BYTES:
        return None  # Frame synchronization error

    payload_bytes = read_exact(sock, data_len) if data_len > 0 else b""
    if payload_bytes is None:
        return None

    computed_checksum = calculate_crc32(payload_bytes)
    is_valid = (computed_checksum == received_checksum)

    return seq_no, frame_type, payload_bytes, received_checksum, ecc_bytes, is_valid


# ============================================================================
# ERROR SIMULATION
# ============================================================================

def corrupt_payload(payload_bytes: bytes) -> bytes:
    """Simulates physical channel noise by flipping a single bit in the payload."""
    if not payload_bytes:
        return payload_bytes
    ba = bytearray(payload_bytes)
    byte_idx = random.randint(0, len(ba) - 1)
    bit_idx = random.randint(0, 7)
    ba[byte_idx] ^= (1 << bit_idx)
    return bytes(ba)


def corrupt_ecc_bytes(ecc_bytes: bytes) -> bytes:
    """Flips a single bit in the 2-byte Hamming ECC field to demonstrate FEC."""
    ba = bytearray(ecc_bytes)
    byte_idx = random.randint(0, len(ba) - 1)
    bit_idx = random.randint(0, 6)  # 7-bit codeword
    ba[byte_idx] ^= (1 << bit_idx)
    return bytes(ba)
