"""Cisco Enterprise MIB definitions.

Every OID under ``1.3.6.1.4.1.9`` lives in this package.  The generic SNMP
collector and the MikroTik collector must never import these constants.
"""

CDP_PREFIX = "1.3.6.1.4.1.9.9.23.1.2.1.1"
CDP_COLUMNS = {
    "address_type": f"{CDP_PREFIX}.3",
    "address": f"{CDP_PREFIX}.4",
    "version": f"{CDP_PREFIX}.5",
    "device_id": f"{CDP_PREFIX}.6",
    "device_port": f"{CDP_PREFIX}.7",
    "platform": f"{CDP_PREFIX}.8",
    "capabilities": f"{CDP_PREFIX}.9",
    "native_vlan": f"{CDP_PREFIX}.17",
    "duplex": f"{CDP_PREFIX}.18",
}

# CISCO-PROCESS-MIB cpmCPUTotalTable.
CPU_PREFIX = "1.3.6.1.4.1.9.9.109.1.1.1.1"
CPU_COLUMNS = {
    "physical_index": f"{CPU_PREFIX}.2",
    "five_seconds": f"{CPU_PREFIX}.6",
    "one_minute": f"{CPU_PREFIX}.7",
    "five_minutes": f"{CPU_PREFIX}.8",
}

# CISCO-MEMORY-POOL-MIB ciscoMemoryPoolTable.
MEMORY_PREFIX = "1.3.6.1.4.1.9.9.48.1.1.1"
MEMORY_COLUMNS = {
    "name": f"{MEMORY_PREFIX}.2",
    "used": f"{MEMORY_PREFIX}.5",
    "free": f"{MEMORY_PREFIX}.6",
}

# CISCO-ENVMON-MIB.
ENVMON_VOLTAGE_VALUE = "1.3.6.1.4.1.9.9.13.1.2.1.3"
ENVMON_VOLTAGE_STATE = "1.3.6.1.4.1.9.9.13.1.2.1.7"
ENVMON_TEMPERATURE_VALUE = "1.3.6.1.4.1.9.9.13.1.3.1.3"
ENVMON_TEMPERATURE_VALUE_REV1 = "1.3.6.1.4.1.9.9.13.1.3.1.7"
ENVMON_TEMPERATURE_STATE = "1.3.6.1.4.1.9.9.13.1.3.1.6"
ENVMON_FAN_STATE = "1.3.6.1.4.1.9.9.13.1.4.1.3"
ENVMON_SUPPLY_STATE = "1.3.6.1.4.1.9.9.13.1.5.1.3"

# CISCO-STACKWISE-MIB cswSwitchInfoTable.
STACKWISE_PREFIX = "1.3.6.1.4.1.9.9.500.1.2.1.1"
STACKWISE_COLUMNS = {
    "role": f"{STACKWISE_PREFIX}.3",
    "software_priority": f"{STACKWISE_PREFIX}.4",
    "hardware_priority": f"{STACKWISE_PREFIX}.5",
    "state": f"{STACKWISE_PREFIX}.6",
    "mac_address": f"{STACKWISE_PREFIX}.7",
    "software_image": f"{STACKWISE_PREFIX}.8",
}

# CiscoEnvMonState values.
ENVMON_STATE_NORMAL = 1
ENVMON_STATE_NOT_PRESENT = 5
ENVMON_STATE_NAMES = {
    1: "normal",
    2: "warning",
    3: "critical",
    4: "shutdown",
    5: "notPresent",
    6: "notFunctioning",
}

# cswSwitchRole values.
STACKWISE_ROLE_NAMES = {
    1: "master",
    2: "member",
    3: "notMember",
    4: "standby",
}

# cswSwitchState values.
STACKWISE_STATE_NAMES = {
    1: "waiting",
    2: "progressing",
    3: "added",
    4: "ready",
    5: "sdmMismatch",
    6: "verMismatch",
    7: "featureMismatch",
    8: "newMasterInit",
    9: "provisioned",
    10: "invalid",
    11: "removed",
}

# CDP capability bit map (cdpCacheCapabilities).
CDP_CAPABILITIES = (
    "router",
    "transparentBridge",
    "sourceBridge",
    "switch",
    "host",
    "igmp",
    "repeater",
)
