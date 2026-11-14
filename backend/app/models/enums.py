import enum


class DeviceType(str, enum.Enum):
    ROUTER = "router"
    SWITCH = "switch"
    FIREWALL = "firewall"
    SERVER = "server"
    ACCESS_POINT = "access_point"
    OTHER = "other"


class DeviceCheckType(str, enum.Enum):
    PING_ONLY = "ping_only"
    SNMP = "snmp"
    ROUTEROS_API = "routeros_api"
    RESTCONF = "restconf"


class OsFamily(str, enum.Enum):
    ROUTEROS = "routeros"
    IOS = "ios"
    IOSXE = "iosxe"
    NXOS = "nxos"
    LINUX = "linux"


class CollectorType(str, enum.Enum):
    GENERIC = "generic_snmp"
    MIKROTIK = "mikrotik"
    CISCO = "cisco"
