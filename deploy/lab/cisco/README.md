# Cisco IOS-XE lab node

This directory defines an optional Containerlab node for testing the `cisco`
collector and Cisco enterprise OIDs. Nothing here is required for the normal
Docker Compose stack.

> Cisco IOS-XE images are licensed. You must supply your own CSR1000v or
> Cat8000v image (for example built with
> [vrnetlab](https://github.com/hellt/vrnetlab)). Do not commit images,
> licenses, or real credentials.

## Prerequisites

- Docker with at least 4 GB free RAM and KVM acceleration if available.
- [Containerlab](https://containerlab.dev/) installed on the host.
- The compose lab stack running, because it creates the `mgkk-cisco-lab`
  network and attaches `poller-worker` to it:

  ```powershell
  docker compose --env-file .env.lab -f compose.yaml -f deploy/docker-compose.lab.yml up --build -d
  ```

## 1. Configure lab credentials

Add these values to `.env.lab` (see `.env.lab.example`):

| Variable | Purpose |
| --- | --- |
| `CISCO_IOSXE_IMAGE` | Licensed vrnetlab image, e.g. `vrnetlab/cisco_csr1000v:17.03.04` |
| `LAB_CISCO_HOST` | Management IP of the node, e.g. `172.31.50.10`; leave empty to skip the Cisco checks |
| `LAB_CISCO_RESTCONF_USER` | Local privilege-15 user for optional RESTCONF |
| `LAB_CISCO_RESTCONF_PASSWORD` | Password for that user |
| `LAB_CISCO_SNMP_V3_USER` | SNMPv3 authPriv user (defaults to `LAB_SNMP_V3_USER`) |

SNMPv3 reuses `LAB_SNMP_V3_AUTH_PASSPHRASE` and
`LAB_SNMP_V3_PRIV_PASSPHRASE`, so the poller credential profile can be shared
with the Linux `snmp-lab` target.

## 2. Render the startup configuration

```powershell
uv run python backend/scripts/render_cisco_lab_config.py
```

This writes the ignored `.lab/cisco-lab-startup.cfg` with the SNMPv3 authPriv
user, the RESTCONF user, and the poller subnet bindings. Keep it private.

## 3. Deploy the node

```powershell
containerlab deploy -t deploy/lab/cisco/cisco-iosxe.clab.yml
```

The topology attaches `cisco-iosxe` to `mgkk-cisco-lab` with the static
management address `172.31.50.10` (change `mgmt-ipv4` and `LAB_CISCO_HOST`
together if needed). With KVM the node boots in a few minutes; without KVM
expect a slow software-emulated boot.

The generated config enables:

- SNMPv3 `authPriv` (SHA-1 authentication, AES-128 privacy), read-only view.
- HTTPS RESTCONF on port 443 for the optional Cisco RESTCONF check.
- SSH with a local privilege-15 user.

Verify from the poller container:

```powershell
docker compose --env-file .env.lab -f compose.yaml -f deploy/docker-compose.lab.yml exec poller-worker python scripts/verify_lab.py
```

The script walks `CISCO-PROCESS-MIB` (`cpmCPUTotal1minRev`) over SNMPv3,
confirms `sysObjectID` is under the Cisco enterprise tree (`1.3.6.1.4.1.9`),
and reads the IOS-XE version over RESTCONF when
`LAB_CISCO_RESTCONF_USER`/`LAB_CISCO_RESTCONF_PASSWORD` are set. If the Cisco
node is not running, the check is reported as skipped unless
`LAB_CISCO_REQUIRED=true` is set.

## Teardown

```powershell
containerlab destroy -t deploy/lab/cisco/cisco-iosxe.clab.yml
```
