module.exports = {
  apps: [
    {
      name: 'sonia-ai-companion',
      script: 'npx',
      args: 'serve dist -l 3000',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      env: {
        NODE_ENV: 'production'
      }
    }
  ]
};
