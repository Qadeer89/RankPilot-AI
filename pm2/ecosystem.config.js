// PM2 process definitions for the shared VPS (SYSTEM_ARCHITECTURE.md #7).
// Run from the repo root: pm2 start pm2/ecosystem.config.js
//
// Worker concurrency starts at 1 on the shared pilot VPS until load-tested
// (SYSTEM_ARCHITECTURE.md #6); do not raise it without measuring headroom.
module.exports = {
  apps: [
    {
      name: "rankpilot-web",
      cwd: "../apps/web",
      script: "npx",
      args: "next start -p 3000",
    },
    {
      name: "rankpilot-api",
      cwd: "../apps/api",
      script: ".venv/bin/uvicorn",
      args: "app.main:app --host 127.0.0.1 --port 8000",
    },
    {
      name: "rankpilot-worker",
      cwd: "../apps/api",
      script: ".venv/bin/celery",
      args: "-A app.celery_app worker --concurrency 1",
    },
    {
      name: "rankpilot-scheduler",
      cwd: "../apps/api",
      script: ".venv/bin/celery",
      args: "-A app.celery_app beat",
    },
  ],
};
