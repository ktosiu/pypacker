import struct
import logging

logger = logging.getLogger("pypacker")


class MetaPacket(type):
	"""
	This Metaclass is a more efficient way of setting attributes than using __init__.
	This is done by reading name, format and default value out of __hdr__ in every subclass.
	This configuration is set one time when loading the module (not at instatiation).
	Attributes can be normally accessed using "obj.field" notation.
	General note: Callflaw is: __new__ (loading module) -> __init__ (initiate class)

	CAUTION:
	- List et al are _SHARED_ among all instantiated classes! A copy is needed on changes to them
	- New protocols: don't use header fields having same name as methods in Packet class
	"""

	def __new__(cls, clsname, clsbases, clsdict):
		# Using properties will slow down access to header fields but it's needed:
		# This way we get informed about get-access more efficiently than using
		# __getattribute__ (slow access for header fields vs. slow access
		# for ALL class fields).
		def get_setter(varname, is_field_type_simple=True, is_field_static=True):
			"""
			varname -- name of the variable to set the property for
			is_field_type_simple -- get property for simple static or dynamic type if True, else TriggerList
			is_field_static -- if is_field_type_simple is True: get static type (int, fixed size bytes, ...),
				else dynamic (format "xs") which can change in format (eg DNS names)

			return -- set-property for simple types or triggerlist
			"""
			varname_shadowed = "_%s" % varname

			def setfield_simple(obj, value):
				"""
				Unpack field ondemand
				"""
				if obj._unpacked is not None and not obj._unpacked:
					# obj._unpacked = None means: dissect not yet finished
					obj._unpack()
				if value is None and obj.__getattribute__(varname_shadowed + "_active"):
					object.__setattr__(obj, varname_shadowed + "_active", False)
					obj._header_format_changed = True
					# logger.debug("deactivating field: %s" % varname_shadowed)
				elif value is not None and not obj.__getattribute__(varname_shadowed + "_active"):
					object.__setattr__(obj, varname_shadowed + "_active", True)
					obj._header_format_changed = True
					# logger.debug("activating field: %s" % varname_shadowed)
				if not is_field_static and value is not None:
					# simple dynamic field
					format_new = "%ds" % len(value)
					# logger.debug(">>> changing format for dynamic field: %r / %s / %s" % (obj.__class__, varname_shadowed, format_new))
					object.__setattr__(obj, varname_shadowed + "_format", format_new)
					obj._header_format_changed = True

				object.__setattr__(obj, varname_shadowed, value)
				obj._header_changed = True
				obj._notify_changelistener()

			def setfield_triggerlist(obj, value):
				"""
				Clear list and add value as only value.

				value -- Packet, bytes (single or as list)
				"""
				tl = obj.__getattribute__(varname_shadowed)

				if type(tl) is list:
					# we need to create the original TriggerList in order to unpack correctly
					# _triggerlistName = [b"bytes", callback] or
					# _triggerlistName = [b"", callback] (default initiation)
					# logger.debug(">>> initiating TriggerList")
					tl = obj._header_fields_dyn_dict[varname_shadowed](obj, dissect_callback=tl[1], buffer=tl[0])
					object.__setattr__(obj, varname_shadowed, tl)
				# this will trigger unpacking

				del tl[:]

				# TriggerList: avoid overwriting dynamic fields eg when using keyword constructor Class(key=val)
				if type(value) is list:
					tl.extend(value)
				else:
					tl.append(value)
				obj._header_changed = True
				obj._notify_changelistener()

			if is_field_type_simple:
				return setfield_simple
			else:
				return setfield_triggerlist

		def get_getter(varname, is_field_type_simple=True):
			"""
			varname -- name of the variable to set the property for
			is_field_type_simple -- get property for simple static or dynamic type if True, else TriggerList
			return -- get-property for simple type or triggerlist
			"""
			varname_shadowed = "_%s" % varname

			def getfield_simple(obj):
				"""
				Unpack field ondemand
				"""
				# logger.debug("getting value for simple field: %s" % varname_shadowed)
				if obj._unpacked is not None and not obj._unpacked:
					obj._unpack()
				# logger.debug("now returning value")
				return obj.__getattribute__(varname_shadowed)

			def getfield_triggerlist(obj):
				tl = obj.__getattribute__(varname_shadowed)
				# logger.debug(">>> getting Triggerlist for %r: %r" % (obj.__class__, tl))

				if type(tl) is list:
					# _triggerlistName = [b"bytes", callback] or
					# _triggerlistName = [b"", callback] (default initiation)
					tl = obj._header_fields_dyn_dict[varname_shadowed](obj, dissect_callback=tl[1], buffer=tl[0])
					object.__setattr__(obj, varname_shadowed, tl)

				return tl

			if is_field_type_simple:
				return getfield_simple
			else:
				return getfield_triggerlist

		t = type.__new__(cls, clsname, clsbases, clsdict)
		# dictionary of TriggerLists: name -> TriggerListClass
		t._header_fields_dyn_dict = {}
		# get header-infos from subclass: [("name", "format", value), ...]
		hdrs = getattr(t, "__hdr__", None)
		# cache header for performance reasons, will be set to bytes later on
		t._header_cached = []
		# all header names
		t._header_field_names = []
		t._header_format_order = getattr(t, "__byte_order__", ">")
		# all header formats including byte order
		header_fmt = [t._header_format_order]

		if hdrs is not None:
			# every header var will get two additional values set:
			# var_active = indicates if header is active
			# var_format = indicates the header format
			# logger.debug("loading meta for: %s, st: %s" % (clsname, st))
			for hdr in hdrs:
				shadowed_name = "_%s" % hdr[0]
				t._header_field_names.append(shadowed_name)
				setattr(t, shadowed_name + "_active", True)

				# remember header format
				# t._header_field_infos[shadowed_name] = [True, hdr[1]]
				is_field_type_simple = False
				is_field_static = True

				if hdr[1] is not None or (hdr[2] is None or type(hdr[2]) == bytes):
					# simple static or simple dynamic type
					# we got one of: ("name", format, ???) = static or
					# ("name", None, ???) = dynamic
					# -> Format given = static, Format None = dynamic
					is_field_type_simple = True

					if hdr[1] is None:
						# assume simple dynamic field
						is_field_static = False

				setattr(t, shadowed_name + "_format", hdr[1])

				if is_field_type_simple:
					fmt = hdr[1]

					if hdr[2] is not None:
						# value given: field is active
						if fmt is None:
							# dynamic field
							fmt = "%ds" % len(hdr[2])
							setattr(t, shadowed_name + "_format", fmt)
						header_fmt.append(fmt)
						t._header_cached.append(hdr[2])
						"""
						if fmt is not None:
							header_fmt.append(fmt)
							t._header_cached.append(hdr[2])
						"""
						# logger.debug("--------> field is active: %r" % hdr[0])
					else:
						setattr(t, shadowed_name + "_active", False)

					# only simple fields can get deactivated
					setattr(t, shadowed_name + "_active", True if hdr[2] is not None else False)

					# set initial value via shadowed variable: _varname <- varname [optional in subclass: <- varname_s]
					# setting/getting value is done via properties.
					# logger.debug("init simple type: %s=%r" % (shadowed_name, hdr[2]))
					setattr(t, shadowed_name, hdr[2])
					setattr(t, hdr[0], property(
							get_getter(hdr[0], is_field_type_simple=True),
							get_setter(hdr[0], is_field_type_simple=True, is_field_static=is_field_static)
						)
							)
				else:
					# assume TriggerList
					# Triggerlists don't have initial default values (and can't get deactivated) TODO?
					t._header_fields_dyn_dict[shadowed_name] = hdr[2]
					# initial value of TiggerLists is: values to init empty list
					setattr(t, shadowed_name, [b"", None])
					setattr(t, hdr[0], property(
							get_getter(hdr[0], is_field_type_simple=False),
							get_setter(hdr[0], is_field_type_simple=False, is_field_static=is_field_static)
								)
					)
					# format and value needed for correct length in _unpack()
					header_fmt.append("0s")
					t._header_cached.append(b"")
			# logger.debug("<<<<")

		# logger.debug(">>> translated header names: %s/%r" % (clsname, t._header_name_translate))
		# current format as string
		t._header_format = struct.Struct("".join(header_fmt))
		# header size can be assigened by __init__() directly or given by _header_format.size
		t._header_len = t._header_format.size
		# track changes to header format (changes to simple dynamic fields or TriggerList)
		t._header_format_changed = False
		# cached header, return this if nothing changed
		t._header_cached = t._header_format.pack(*t._header_cached)
		# logger.debug("formatstring is: %s" % header_fmt)
		# body as raw byte string (None if handler is present)
		t._body_bytes = b""
		# name of the attribute which holds the object representing the body aka the body handler
		t._bodytypename = None
		# next lower layer: a = b + c -> b will be lower layer for c
		t._lower_layer = None
		# track changes to header values: This is needed for layers like TCP for
		# checksum-recalculation. Set to "True" on changes to header/body values, set to False on "bin()"
		# track changes to header values
		t._header_changed = False
		# track changes to body value like [None | bytes | body-handler] -> [None | bytes | body-handler]
		t._body_changed = False
		# objects which get notified on changes on header or body (shared)
		# TODO: use sets here
		t._changelistener = []
		# lazy handler data: [name, class, bytes]
		t._lazy_handler_data = None
		# indicates the most top layer until which should be unpacked (vs. lazy dissecting = just next upper layer)
		t._target_unpack_clz = None
		# inicates if static header values got already unpacked
		# [True|False] = Status after dissect, None = pre-dissect (not unpacked)
		t._unpacked = None
		# indicates if this packet contains fragmented data saved as body bytes
		t._fragmented = False
		t._dissect_error = False

		return t
