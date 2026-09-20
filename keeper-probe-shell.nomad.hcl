# keeper-probe-shell.nomad.hcl — idle opencode shell on Nomad (no probing).
#
# Same image/auth as keeper-probe, but CMD is overridden to sleep: the
# alloc sits there so a human can `nomad alloc exec` in and tinker with
# the opencode CLI by hand. NO dispatch runs here, NO keeper POSTs, NO
# quota burn — the only CLI calls are the ones you type yourself.
#
# Register (secret flows shell→Nomad only, never git):
#   export NOMAD_ADDR=http://127.0.0.1:4646  # on the box, or tunnel
#   nomad job run \
#     -var=opencode_auth_json="$(cat ~/.local/share/opencode/auth.json)" \
#     keeper-probe-shell.nomad.hcl
# Exec (from anywhere with the management token):
#   TASK=shell ./scripts/nomad-exec.sh keeper-probe-shell
# Inside: `opencode run --pure -m opencode/big-pickle "hello"`.
# Memory fits one manual CLI run (~744MB measured peak); the slot lock
# is irrelevant here (no worker running).

variable "opencode_auth_json" {
  type    = string
  default = "{}"
}

job "keeper-probe-shell" {
  datacenters = ["ovh-vps"]
  type        = "service"

  group "shell" {
    count = 1

    task "shell" {
      driver = "docker"
      config {
        image        = "registry.pkubelka.cz/keeper-probe:main-act2"
        force_pull   = true
        network_mode = "host"
        command      = "sleep"
        args         = ["infinity"]
      }

      env {
        OPENCODE_AUTH_FILE = "${NOMAD_SECRETS_DIR}/opencode-auth.json"
      }

      template {
        data        = var.opencode_auth_json
        destination = "${NOMAD_SECRETS_DIR}/opencode-auth.json"
        change_mode = "restart"
      }

      resources {
        cpu    = 500
        memory = 1024
      }
    }
  }
}
