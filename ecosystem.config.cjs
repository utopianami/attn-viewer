"use strict";

const root = "/home/ryze_yn/attn-viewer";
const pm2Logs = "/home/ryze_yn/.pm2/logs";

const common = {
  instances: 1,
  exec_mode: "fork",
  time: true,
  autorestart: true,
  restart_delay: 5_000,
  exp_backoff_restart_delay: 100,
  min_uptime: "10s",
  max_restarts: 10,
  kill_timeout: 30_000,
};

const apps = [
  {
    ...common,
    name: "attn-viewer",
    cwd: root,
    script: `${root}/server.mjs`,
    interpreter: "/usr/bin/node",
    max_memory_restart: "1G",
    out_file: `${pm2Logs}/attn-viewer-out.log`,
    error_file: `${pm2Logs}/attn-viewer-error.log`,
  },
  {
    ...common,
    name: "attn-engine",
    cwd: root,
    script: `${root}/engine/.venv/bin/uvicorn`,
    args: "engine.app.main:app --host 127.0.0.1 --port 8801",
    interpreter: "none",
    max_memory_restart: "3G",
    out_file: `${pm2Logs}/attn-engine-out.log`,
    error_file: `${pm2Logs}/attn-engine-error.log`,
  },
  {
    ...common,
    name: "attn-scheduler",
    cwd: `${root}/engine`,
    script: `${root}/engine/.venv/bin/python`,
    args: "-m app.scheduler_worker",
    interpreter: "none",
    max_memory_restart: "2G",
    out_file: `${pm2Logs}/attn-scheduler-out.log`,
    error_file: `${pm2Logs}/attn-scheduler-error.log`,
  },
  {
    ...common,
    name: "attn-vault-bridge",
    cwd: root,
    script: `${root}/scripts/vault-bridge.mjs`,
    interpreter: "/usr/bin/node",
    max_memory_restart: "256M",
    out_file: `${pm2Logs}/attn-vault-bridge-out.log`,
    error_file: `${pm2Logs}/attn-vault-bridge-error.log`,
  },
];

if (process.env.ATTN_NGROK_ENABLED === "1") {
  apps.push({
    ...common,
    name: "attn-ngrok",
    cwd: root,
    script: `${root}/scripts/tunnel.mjs`,
    interpreter: "/usr/bin/node",
    autorestart: false,
    max_memory_restart: "256M",
    out_file: `${pm2Logs}/attn-ngrok-out.log`,
    error_file: `${pm2Logs}/attn-ngrok-error.log`,
  });
}

module.exports = { apps };
