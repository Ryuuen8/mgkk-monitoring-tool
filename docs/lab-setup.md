# Isolated Phase 0 network lab

The optional lab override adds a Debian `snmpd` target and a RouterOS CHR
virtual machine. The CHR image is a community QEMU wrapper, not an official
MikroTik container image; review and pin the image before using it in a
controlled environment. The poller joins an isolated Docker bridge for these
targets and retains `NET_RAW` for ICMP. Do not attach production devices or
credentials to this lab.

## Start the lab

1. Copy `.env.lab.example` to `.env.lab` and replace every placeholder with
   unique, lab-only values. Use alphanumeric characters and `._+-` in
   passphrases so they work in the generated SNMP configuration. Keep the
   subnet consistent with the poller's lab bridge; use a subnet that does not
   overlap your local or Docker networks.
2. Start the stack and lab targets:

   ```powershell
   docker compose --env-file .env.lab -f compose.yaml -f deploy/docker-compose.lab.yml up --build -d
   ```

   The RouterOS image runs CHR under QEMU. Initial boot can take several
   minutes without hardware virtualization. WebFig is bound to
   `http://localhost:8080`; HTTPS REST is bound to `https://localhost:8443`.
   The SNMP target is not published to the host and is reachable only from the
   lab network.

3. Generate the RouterOS setup commands:

   ```powershell
   uv run python backend/scripts/render_routeros_lab_setup.py
   ```

   Open the ignored, local-only `.lab/routeros-readonly-setup.rsc` file and
   paste its contents into the CHR terminal in WebFig. It creates a
   `group=read` monitoring user limited to the poller subnet, enables
   `www-ssl` with a self-signed lab certificate, removes the default `public`
   SNMP community, and adds a read-only community limited to that subnet.
   The generated file contains credentials; keep it private and remove it
   after applying the configuration.

4. Run all connectivity checks from the same container that polls devices:

   ```powershell
   docker compose --env-file .env.lab -f compose.yaml -f deploy/docker-compose.lab.yml exec poller-worker python scripts/verify_lab.py
   ```

   The script checks three ICMP probes, an SNMPv2c walk, an SNMPv3 authPriv
   walk, and an authenticated RouterOS REST request. It exits non-zero and
   reports the failing check if any target is unreachable or credentials do
   not work.

The `snmp-lab` agent restricts its v2c community to the poller subnet and
requires SNMPv3 authPriv for its v3 user. It exposes only the system MIB view
for these checks. RouterOS API/TLS and SNMP access are restricted to the lab
subnet; host-published management ports are bound to loopback only.

## Stop and reset

```powershell
docker compose --env-file .env.lab -f compose.yaml -f deploy/docker-compose.lab.yml down
```

CHR state is kept under the ignored `.lab/routeros` directory. Remove that
specific directory if you want to reset the virtual router; keep `.env.lab`
and the generated setup file private.
