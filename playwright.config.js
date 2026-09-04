const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests/browser',
  timeout: 30_000,
  fullyParallel: false,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:4177',
    browserName: 'chromium',
    headless: true,
    screenshot: 'only-on-failure'
  },
  webServer: {
    command: 'python3 -m http.server 4177 --bind 127.0.0.1 --directory docs/demo',
    url: 'http://127.0.0.1:4177',
    reuseExistingServer: true,
    timeout: 10_000
  }
});
