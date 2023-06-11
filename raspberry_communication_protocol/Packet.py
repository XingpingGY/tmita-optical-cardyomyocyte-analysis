from __future__ import annotations

import io
import struct

import crc
import numpy as np

from raspberry_communication_protocol.PacketType import PacketType


class Packet:
    """
    Content description of a packet that implements
    a custom Application Layer communication protocol.

    We use this class to be able to send NumPy array, representing video frames,
    from one computer to another. The base usage was a RaspberryPi grabbing video frames,
    and sending them over Ethernet.

    Please read the given md file for more information on this protocol
    """
    # Frames can get corrupted during transport because of their size.
    # A 16-bit CRC should cover enough unique values for integrity checks
    CRC_COMPUTER = crc.Calculator(crc.Crc16.CCITT.value)
    BYTE_ORDER = "big"
    # Defining the protocol's values here. Sizes are defined in number of **bytes** unless mentioned otherwise
    PROTOCOL_VER = 0b10

    START_MAGIC_WORD = b"inu"
    """Magic start word in buffer"""
    END_MAGIC_WORD = b"neko"
    """Magic end word in buffer"""

    # -- definition of sizes in the protocol
    LEN_START_MAGIC_WORD = len(START_MAGIC_WORD)
    """Number of bytes of the magic start word"""
    LEN_PROVER_PTYPE_CCOUNT = 1  # Protocol version, PacketType, Channel count and padding
    """Number of byte that singlehandedly contains protocol version, packet type and frame channel count"""

    # -- The 3 following sizes describe numbers of **bits**
    BIT_LEN_PROTOCOL_VER = 2
    """Number of bits for the protocol's version"""
    BIT_LEN_PACKET_TYPE = 2
    """Number of bits for the type of packet sent"""
    BIT_LEN_CHANNEL_COUNT = 2
    """Number of bits for the number of channels of the video frame"""
    # --

    # The following are now number of **bytes**
    LEN_FRAME_NUMBER = 4
    """Number of bytes used for the number that specifies what is
    the current number of the frame"""
    LEN_FRAME_XY_SHAPE = 4
    """Number of bytes for the x and y shape of the video frame (2 bytes each)"""
    LEN_PAYLOAD_LENGTH = 4
    """Number of bytes for the number that contains
    the payload's length (i.e. the number of bytes that we have to read
    to grab the whole payload)"""
    # actual payload's length is computed during runtime
    LEN_PAYLOAD_CRC = 2  # because we use Crc16
    """Number of bytes of the CRC value"""
    LEN_END_MAGIC_WORD = len(END_MAGIC_WORD)
    """Number of bytes of the magic start word"""

    PAYLOAD_LEN_IDX = sum((LEN_START_MAGIC_WORD, LEN_PROVER_PTYPE_CCOUNT,
                           LEN_FRAME_NUMBER, LEN_FRAME_XY_SHAPE))
    """Start index of the bytes describing the payload's length"""
    # Format string used during serialization
    # Specifies the type of the objects sent, the first character defines the endianness (big here)
    # Read the official documentation of struct.pack() for more details
    # You need to update it according to the above ! Otherwise, tests will fail !
    PACKING_FORMAT_START = \
        "!" \
        f"{LEN_START_MAGIC_WORD}s" \
        f"{LEN_PROVER_PTYPE_CCOUNT}c" \
        "I" \
        f"{LEN_FRAME_XY_SHAPE//2}H" \
        "I"
    """Start of the formatting used by struct.pack(), to serialize the packet."""

    PACKING_FORMAT_END = \
        f"{LEN_PAYLOAD_CRC}s" \
        f"{LEN_END_MAGIC_WORD}s"
    """End of the formatting used by struct.pack(), to serialize the packet."""

    def __init__(self, frame_number: int, packet_type: PacketType, payload: np.ndarray):
        self.frame_number = frame_number
        self.packet_type = packet_type
        self.frame_shape = payload.shape[:2]
        if len(payload.shape) <= 2:
            self.frame_channel_count = 1
        else:
            self.frame_channel_count = payload.shape[2]
        self.payload = payload
        """Big warning: payload must have int as its data type, otherwise NumPy will fail to convert the bytes"""
        # CRC is computed over packet's unique data
        self.payload_crc = Packet.compute_crc(self)

    def payload_length(self):
        """Returns the number of **bytes** required to store this payload."""
        return len(self.payload.tobytes())

    def __eq__(self, other):
        if type(other) != Packet:
            return False
        return self.frame_number == other.frame_number \
            and self.packet_type == other.packet_type \
            and self.payload_crc == other.payload_crc \
            and self.payload.shape == other.payload.shape \
            and (self.payload == other.payload).all()

    def serialize(self) -> bytes:
        """Serialize this packet's content and returns the binary string"""
        # We concat ProtocolVer and PacketType to save some space and use only a single byte for their storage
        # Please check `comm_protocol_definition.md` for more details
        proto_ptype_channelcount = (Packet.PROTOCOL_VER << 6
                                    | self.packet_type.value << 4
                                    | self.frame_channel_count << 2)
        proto_ptype_channelcount_bytes = proto_ptype_channelcount.to_bytes(1, "big")

        # Compute payload length to find the shape of the format
        # to use with struct.pack()
        actual_payload_length = self.payload_length()
        actual_payload_length_format = Packet.compute_payload_ser_format(actual_payload_length)
        data = struct.pack(
            Packet.PACKING_FORMAT_START + actual_payload_length_format + Packet.PACKING_FORMAT_END,
            Packet.START_MAGIC_WORD,
            proto_ptype_channelcount_bytes,
            self.frame_number,
            *self.frame_shape[:2],
            self.payload_length(),
            self.payload.tobytes(),
            self.payload_crc.to_bytes(Packet.LEN_PAYLOAD_CRC, byteorder="little"),
            Packet.END_MAGIC_WORD
        )
        return data

    @staticmethod
    def compute_crc(packet: Packet):
        """Computes and returns the payload's CRC when converted to bytes using NumPy's tobytes() method"""
        return Packet.CRC_COMPUTER.checksum(packet.payload.tobytes())

    @staticmethod
    def compute_payload_ser_format(payload_length: int) -> str:
        """With the payload's length, determines the format used by struct.pack()"""
        return f"{payload_length}s"

    @classmethod
    def bytes_to_int(cls, data: bytes):
        """Converts the given data to an int, using this class' byte order"""
        return int.from_bytes(data, cls.BYTE_ORDER)

    @classmethod
    def placeholder(cls) -> Packet:
        """Returns a placeholder Packet object, its values are meant to be replaced, not used. Convenience method"""
        return Packet(-1, PacketType.OK, np.array(()))

    @classmethod
    def deserialize(cls, raw_packet: bytes) -> Packet | None:
        """Deserializes a packet, and returns a Packet object. Returns None in case of protocol or CRC mismatch"""

        # find payload's format in the raw packet
        payload_length = raw_packet[cls.PAYLOAD_LEN_IDX: cls.PAYLOAD_LEN_IDX + cls.LEN_PAYLOAD_LENGTH]
        payload_length = cls.bytes_to_int(payload_length)
        payload_length_format = cls.compute_payload_ser_format(payload_length)

        # extract data from bytes
        format = cls.PACKING_FORMAT_START + payload_length_format + cls.PACKING_FORMAT_END
        packed_data = struct.unpack(format, raw_packet)
        print(packed_data)

        # unpack into variables, and convert into ints
        _, prover_ptype_ccount, frame_number, frame_x_shape, frame_y_shape, _, payload_bin, payload_crc, _ = packed_data
        prover_ptype_ccount = cls.bytes_to_int(prover_ptype_ccount)
        payload_crc = cls.bytes_to_int(payload_crc)

        # extract data from the special byte containing
        # protocol ver, packet type and num of channels in video frame
        prover_ptype_ccount_bin = bin(prover_ptype_ccount)[2:]

        proto_ver = prover_ptype_ccount_bin[:cls.BIT_LEN_PROTOCOL_VER]
        if int(proto_ver, 2) != cls.PROTOCOL_VER:
            return

        packet_type_bin = prover_ptype_ccount_bin[
                cls.BIT_LEN_PROTOCOL_VER
                :
                cls.BIT_LEN_PROTOCOL_VER + cls.BIT_LEN_PACKET_TYPE
        ]
        packet_type = PacketType(int(packet_type_bin, 2)).name

        frame_channel_count = prover_ptype_ccount_bin[
            cls.BIT_LEN_PROTOCOL_VER + cls.BIT_LEN_PACKET_TYPE
            :
            cls.BIT_LEN_PROTOCOL_VER + cls.BIT_LEN_PACKET_TYPE + cls.BIT_LEN_CHANNEL_COUNT
        ]
        frame_channel_count = int(frame_channel_count, 2)

        # reshape payload
        payload = np.frombuffer(payload_bin, dtype=int)
        shape = (frame_x_shape, frame_y_shape, frame_channel_count)
        payload = payload.reshape(shape)

        # check if payload crc is valid
        if payload_crc == cls.CRC_COMPUTER.checksum(payload_bin):
            return

        # assign to packet object
        deserialized = cls.placeholder()
        deserialized.packet_type = packet_type
        deserialized.frame_channel_count = frame_channel_count
        deserialized.frame_number = frame_number
        deserialized.frame_shape = shape
        deserialized.payload = payload

        return deserialized


if __name__ == '__main__':
    # TODO: if filled with 0s, crashes
    og_payload = np.full((2, 2, 3), 4, dtype=int)
    print(og_payload)
    p = Packet(0xFA, PacketType.FRAME, og_payload)
    s = p.serialize()
    print(s)
    pds = Packet.deserialize(s)
    print(pds.payload)
