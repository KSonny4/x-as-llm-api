# keeper-probe.nomad.hcl — ON-DEMAND dual prober (Nomad batch job).
#
# Runs probe/dispatch.py in-cluster: L1 curl always, L2 opencode CLI only
# on L1 non-ok; results POST back to keeper /api/v1/probe so the matrix,
# /metrics and the Grafana alert see fresh dual verdicts.
#
# Register (secrets NEVER in git — pass via -var):
#   export NOMAD_ADDR=https://nomad.pkubelka.cz
#   export NOMAD_TOKEN=$(bao kv get -field=management secret/projects/NomadSetup/acl)
#   nomad job run \
#     -var=keeper_token="$(bao kv get -field=token secret/projects/pi-infinity-llm/KEEPER_TOKEN)" \
#     -var=seeds_json="$(cat /tmp/seeds-live.json)" \
#     -var=opencode_auth_json="$(cat ~/.local/share/opencode/auth.json)" \
#     keeper-probe.nomad.hcl
#
# Dispatch on demand (e.g. when L1 fails, or on a schedule you own):
#   nomad job dispatch keeper-probe
# Then: keeper matrix refresh (?refresh=1) shows fresh l2 verdicts.
#
# Zen L1 egress (M3 adoption 2026-09-19): base URLs point at the
# keeper-zen-egress Cloudflare Worker (see probe/egress/worker.js),
# which returned keyed 200 where OVH direct returns 403. The sing-box
# sidecar experiment (probe/egress/*) is parked: it routes correctly
# but shares one Mullvad key+address with Pi gluetun (conflict →
# blackhole). Revive with a second key; see docs/zen-egress.md.
#
# Notes: network_mode host so the probe reaches keeper on node loopback
# (:8102) without publishing ports. opencode auth arrives as a templated
# file staged by the entrypoint (same secret class as KEEPER_TOKEN:
# holder = Nomad management token only; source of truth stays local
# opencode login / Bao).

variable "keeper_token" {
  type = string
}

variable "seeds_json" {
  type    = string
  default = "{\"routes\": []}"
}

variable "opencode_auth_json" {
  type    = string
  default = "{}"
}

job "keeper-probe" {
  datacenters = ["ovh-vps"]
  type        = "batch"

  parameterized {
    payload = "optional"
  }

  group "probe" {
    count = 1

    task "probe" {
      driver = "docker"
      config {
        image        = "registry.pkubelka.cz/keeper-probe:main-529dd3e"
        force_pull   = true
        network_mode = "host"
      }

      env {
        KEEPER_URL          = "http://127.0.0.1:8102"
        KEEPER_TOKEN        = var.keeper_token
        SEEDS_JSON          = var.seeds_json
        OPENCODE_AUTH_FILE  = "${NOMAD_SECRETS_DIR}/opencode-auth.json"
      }

      template {
        data        = var.opencode_auth_json
        destination = "${NOMAD_SECRETS_DIR}/opencode-auth.json"
        change_mode = "restart"
      }

      # Memory sizing (2026-09-19, MEASURED — see journal
      # 2026-09-19T123000Z-big-pickle-verdict.md): one `opencode run`
      # peaks at ~744MB RSS (`time -l`, 780238848 bytes max). The 256MB
      # cap SIGKILLed every CLI child (rc=-9, empty output) from v19 on.
      # worker.py `_cli_slot` bounds concurrent CLI children to 2 per
      # container, so: 2 x 780MB + ~100MB python + margin = 2048MB.
      # TRADE-OFF: 2GB reservation vs cognee placement (the reason for
      # the 256MB cut that broke L2). Batch job, short-lived; owner
      # decides at re-register. Re-register needs -var=opencode_auth_json
      # (owner-held) — spec change alone does nothing until then.
      resources {
        cpu    = 500
        memory = 2048
      }
    }
  }
}
