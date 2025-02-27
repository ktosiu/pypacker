"""TriggerList for handling dynamic headers."""

import logging

logger = logging.getLogger("pypacker")


class TriggerList(list):
	"""
	List with trigger-capabilities representing a Packet header.
	This list can contain one type of raw bytes, tuples or packets representing an individual
	header field. Using bytes or tuples "_pack()" can be overwritten to reassemble bytes.
	"""
	def __init__(self, packet, dissect_callback=None, buffer=b""):
		"""
		packet -- packet where this TriggerList gets ingegrated
		dissect_callback -- callback which dessects byte string "buffer"
		buffer -- byte string to be dissected
		"""
		# set by external Packet
		#logger.debug(">>> init of TriggerList (contained in %s): %s" % (packet.__class__.__name__, buffer))
		self._packet = packet
		self._dissect_callback = dissect_callback
		self._cached_result = buffer

	def _lazy_dissect(self):
		if not self._packet._unpacked and self._packet._unpacked is not None:
			# Before changing TriggerList we need to unpack or
			# cached header won't fit on _unpack(...)
			# This is called before any changes to TriggerList so place it here.
			# Ignore if TriggerList changed in _dissect (_unpacked is None)
			self._packet._unpack()

		if self._dissect_callback is None:
			# already dissected, ignore
			return

		initial_list_content = self._dissect_callback(self._cached_result)
		self._dissect_callback = None
		super().extend(initial_list_content)

	# Python predefined overwritten methods

	def __getitem__(self, pos):
		self._lazy_dissect()
		return super().__getitem__(pos)

	def __iadd__(self, v):
		"""Item can be added using '+=', use 'append()' instead."""
		self._lazy_dissect()
		super().__iadd__(v)
		self.__refresh_listener([v])
		return self

	def __setitem__(self, k, v):
		self._lazy_dissect()
		try:
			# remove listener from old packet which gets overwritten
			self[k].remove_change_listener(None, remove_all=True)
		except:
			pass
		super().__setitem__(k, v)
		self.__refresh_listener([v])

	def __delitem__(self, k):
		# logger.debug("removing elements: %r" % k)
		self._lazy_dissect()
		if type(k) is int:
			itemlist = [self[k]]
		else:
			# assume slice: [x:y]
			itemlist = self[k]
		super().__delitem__(k)
		# logger.debug("removed, handle mod")
		self.__refresh_listener(itemlist, add_listener=False)
		# logger.debug("finished removing")

	def __len__(self):
		self._lazy_dissect()
		return super().__len__()

	def append(self, v):
		self._lazy_dissect()
		super().append(v)
		# logger.debug("handling mod")
		self.__refresh_listener([v])
		# logger.debug("finished")

	def extend(self, v):
		self._lazy_dissect()
		super().extend(v)
		self.__refresh_listener(v)

	def insert(self, pos, v):
		self._lazy_dissect()
		super().insert(pos, v)
		self.__refresh_listener([v])

	# TODO: pop(...) needed?

	def __refresh_listener(self, val, add_listener=True):
		"""
		Handle modifications of this TriggerList (adding, removing, ...).

		val -- list of bytes, tuples or packets
		add_listener -- re-add listener if True
		"""
		try:
			for v in val:
				# react on changes of packets in this triggerlist
				v._remove_change_listener(None, remove_all=True)
				if add_listener:
					v._add_change_listener(self._notify_change)
		except AttributeError as e:
			# this will fail if val is not a packet
			# logger.debug(e)
			pass

		self._notify_change()
		# logger.debug("handle mod sub: finished")

	def _notify_change(self):
		"""
		Update _header_changed of and _header_format_changed of the Packet having
		this TriggerList as field and _cached_result.
		Called by: this list on changes or Packets in this list
		"""
		try:
			self._packet._header_changed = True
			self._packet._header_format_changed = True
			# logger.debug(">>> TriggerList changed!!!")
		except AttributeError as e:
			# this only works on Packets
			# logger.debug(e)
			pass

		# list changed: old cache of TriggerList not usable anymore
		self._cached_result = None

	__TYPES_TRIGGERLIST_SIMPLE = set([bytes, tuple])

	def bin(self):
		"""
		Output the TriggerLists elements as concatenated bytestring.
		Custom implementations can be set by overwriting _pack().
		"""
		if self._cached_result is None:
			try:
				# logger.debug("calling pack")
				self._cached_result = self._pack()
			except:
				# logger.debug(self)
				# logger.debug("packing packets")
				# logger.debug([pkt.bin() for pkt in self])
				self._cached_result = b"".join([pkt.bin() for pkt in self])
		# logger.debug("new cached result: %s" % self._cached_result)
		return self._cached_result

	def find_pos(self, search_cb, offset=0):
		"""
		Find an item-position giving search callback as search criteria.

		search_cb -- callback to compare values, signature: callback(value) [True|False]
			Return True to return value found.
		offset -- start at index "offset" to search
		return -- index of first element found or None
		"""
		self._lazy_dissect()
		while offset < len(self):
			try:
				if search_cb(self[offset]):
					return offset
			except:
				# error on callback (unknown fields etc), ignore
				pass
			offset += 1
		# logger.debug("position not found")
		return None

	def find_value(self, search_cb, offset=0):
		"""
		Same as find_pos() but directly returning found value or None.
		"""
		self._lazy_dissect()
		try:
			return self[self.find_pos(search_cb, offset=offset)]
		except TypeError:
			return None

	"""
	def _pack(self):
		# This ca  be overwritten to create TriggerLists containing non-Packet values (see layer567/http.py)
		# return -- byte string representation of this triggerlist
		return b"".join(self)
	"""

	def __repr__(self):
		self._lazy_dissect()
		return super().__repr__()

	def __str__(self):
		self._lazy_dissect()
		return super().__str__()
