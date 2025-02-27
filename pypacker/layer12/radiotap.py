"""Radiotap"""
from pypacker import pypacker, triggerlist
import struct
import logging

logger = logging.getLogger("pypacker")

# avoid references for performance reasons
unpack_flags = struct.Struct(">I").unpack
unpack_hdr_len = struct.Struct("<H").unpack

RTAP_TYPE_80211 = 0

# Ref: http://www.radiotap.org
# Fields Ref: http://www.radiotap.org/defined-fields/all

# defined flags ordered by appearance (big endian)
TSFT_MASK		= 0x01000000
FLAGS_MASK		= 0x02000000
RATE_MASK		= 0x04000000
CHANNEL_MASK		= 0x08000000

FHSS_MASK		= 0x10000000
DB_ANT_SIG_MASK		= 0x20000000
DB_ANT_NOISE_MASK	= 0x40000000
LOCK_QUAL_MASK		= 0x80000000

TX_ATTN_MASK		= 0x00010000
DB_TX_ATTN_MASK		= 0x00020000
DBM_TX_POWER_MASK	= 0x00040000
ANTENNA_MASK		= 0x00080000

ANT_SIG_MASK		= 0x00100000
ANT_NOISE_MASK		= 0x00200000
RX_FLAGS_MASK		= 0x00400000

CHANNELPLUS_MASK	= 0x00000400
HT_MASK			= 0x00000800

AMPDU_MASK		= 0x00001000
VHT_MASK		= 0x00002000

# 7 bits reserved

RT_NS_NEXT_MASK		= 0x00000020
VENDOR_NS_NEXT		= 0x00000040
EXT_MASK		= 0x00000080

# mask -> (length, alignment)
RADIO_FIELDS = {
	TSFT_MASK		: (8, 8),
	FLAGS_MASK		: (1, 1),
	RATE_MASK		: (1, 1),
	# channel + flags
	CHANNEL_MASK		: (4, 2),

	# fhss + pattern
	FHSS_MASK		: (2, 1),
	DB_ANT_SIG_MASK 	: (1, 1),
	DB_ANT_NOISE_MASK	: (1, 1),
	LOCK_QUAL_MASK 		: (2, 2),

	TX_ATTN_MASK		: (2, 2),
	DB_TX_ATTN_MASK 	: (2, 2),
	DBM_TX_POWER_MASK 	: (1, 1),
	ANTENNA_MASK		: (1, 1),

	ANT_SIG_MASK 		: (1, 1),
	ANT_NOISE_MASK		: (1, 1),
	RX_FLAGS_MASK 		: (2, 2),

	# CHANNELPLUS_MASK	:,
	HT_MASK			: (3, 1),

	AMPDU_MASK		: (8, 4),
	VHT_MASK		: (12, 2)

	# RT_NS_NEXT_MASK	:,
	# VENDOR_NS_NEXT	:,
	# EXT_MASK		:
}

RADIO_FIELDS_MASKS = [
	TSFT_MASK,
	FLAGS_MASK,
	RATE_MASK,
	# channel + flags
	CHANNEL_MASK,

	# fhss + pattern
	FHSS_MASK,
	DB_ANT_SIG_MASK,
	DB_ANT_NOISE_MASK,
	LOCK_QUAL_MASK,

	TX_ATTN_MASK,
	DB_TX_ATTN_MASK,
	DBM_TX_POWER_MASK,
	ANTENNA_MASK,

	ANT_SIG_MASK,
	ANT_NOISE_MASK,
	RX_FLAGS_MASK,

	HT_MASK,

	AMPDU_MASK,
	VHT_MASK
]


class FlagTriggerList(triggerlist.TriggerList):
	# no __init__ needed: we just add tuples
	def _pack(self):
		return b"".join([flag[1] for flag in self])


def get_channelinfo(channel_bytes):
	"""
	return -- [channel_mhz, channel_flags]
	"""
	return [struct.unpack("<H", channel_bytes[0:2])[0], struct.unpack("<H", channel_bytes[2:4])[0]]


class Radiotap(pypacker.Packet):
	__hdr__ = (
		("version", "B", 0),
		("pad", "B", 0),
		("len", "H", 0x0800),
		("present_flags", "I", 0),
		("flags", None, FlagTriggerList)		# stores: (XXX_MASK, value)
	)

	# handle frame check sequence
	def __get_fcs(self):
		try:
			return self._fcs
		except AttributeError:
			return b""

	def __set_fcs(self, fcs):
		self._fcs = fcs

	fcs = property(__get_fcs, __set_fcs)

	def _dissect(self, buf):
		flags = self._present_flags = unpack_flags(buf[4:8])[0]
		pos_end = len(buf)

		if flags & FLAGS_MASK == FLAGS_MASK:
			off = 0

			if flags & TSFT_MASK == TSFT_MASK:
				off = 8
			if buf[off] & 0x10 != 0:
				logger.debug("fcs found")
				self._fcs = buf[-4:]
				pos_end = -4

		hdr_len = unpack_hdr_len(buf[2:4])[0]
		#logger.debug("hdr length is: %d" % hdr_len)
		self._init_triggerlist("flags", buf[8: hdr_len], self._parse_flags)
		# now we got the correct header length
		self._init_handler(RTAP_TYPE_80211, buf[hdr_len: pos_end])
		#logger.debug(adding %d flags" % len(self.flags))
		return hdr_len

	def _parse_flags(self, buf):
		off = 0
		flags = []

		# assume order of flags is correctly stated by "present_flags"
		# we need to know if fcs is present: minimum TSFT and flags must get parsed
		for mask in RADIO_FIELDS_MASKS:
			#logger.debug(self.present_flags)
			# flag not set
			if mask & self.present_flags == 0:
				continue

			size_align = RADIO_FIELDS[mask]
			size = size_align[0]
			# check alignment
			mod = off % size_align[1]

			if mod != 0:
				# enlarge size by alignment
				size += (size_align[1] - mod)

			# logger.debug("got flag %02X, length/align: %r" % (mask, size_align))
			# add all fields for the stated flag
			value = buf[off: off + size]

			# FCS present?
			if mask == FLAGS_MASK and struct.unpack(">B", value)[0] & 0x10 != 0:
				# logger.debug("fcs found")
				fcs_present = True

			#logger.debug("adding flag: %s" % str(mask))
			flags.append((mask, value))
			off += size
		return flags

	def bin(self, update_auto_fields=True):
		"""Custom bin(): handle FCS."""
		return pypacker.Packet.bin(self, update_auto_fields=update_auto_fields) + self.fcs


# load handler
from pypacker.layer12 import ieee80211

pypacker.Packet.load_handler(Radiotap,
	{
		RTAP_TYPE_80211: ieee80211.IEEE80211
	}
)
