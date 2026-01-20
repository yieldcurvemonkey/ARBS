const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

async function collectPerformanceMetrics() {
  const browser = await puppeteer.launch({ 
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });
  
  const results = {
    timestamp: new Date().toISOString(),
    environment: 'local',
    url: 'http://localhost:3002',
    pages: {}
  };

  try {
    // Test main page
    console.log('Testing main page...');
    results.pages.main = await testPage(browser, 'http://localhost:3002/', 'Main Page');
    
    // Test packages page
    console.log('Testing packages page...');
    results.pages.packages = await testPage(browser, 'http://localhost:3002/packages', 'Packages Page');
    
    // Test analytics page
    console.log('Testing analytics page...');
    results.pages.analytics = await testPage(browser, 'http://localhost:3002/analytics', 'Analytics Page');
    
  } catch (error) {
    console.error('Error collecting metrics:', error);
    results.error = error.message;
  } finally {
    await browser.close();
  }

  // Write results to file
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const filename = `performance-baseline-${timestamp}.json`;
  const filepath = path.join(__dirname, filename);
  
  fs.writeFileSync(filepath, JSON.stringify(results, null, 2));
  console.log(`\nPerformance baseline written to: ${filename}`);
  
  // Print summary
  console.log('\n=== PERFORMANCE BASELINE SUMMARY ===');
  for (const [pageName, metrics] of Object.entries(results.pages)) {
    console.log(`\n${pageName.toUpperCase()}:`);
    console.log(`  First Contentful Paint: ${metrics.fcp}ms`);
    console.log(`  DOM Content Loaded: ${metrics.domContentLoaded}ms`);
    console.log(`  Page Load Complete: ${metrics.loadComplete}ms`);
    console.log(`  API Calls: ${metrics.apiCalls.length}`);
    if (metrics.apiCalls.length > 0) {
      console.log('  API Timings:');
      metrics.apiCalls.forEach(call => {
        console.log(`    ${call.url}: ${call.duration}ms (${call.size} bytes)`);
      });
    }
    console.log(`  Console Logs: ${metrics.consoleLogs.length}`);
  }
  
  return filepath;
}

async function testPage(browser, url, pageName) {
  const page = await browser.newPage();
  const metrics = {
    url,
    pageName,
    navigationStart: 0,
    fcp: 0,
    domContentLoaded: 0,
    loadComplete: 0,
    apiCalls: [],
    consoleLogs: [],
    performanceLogs: []
  };

  // Capture console logs
  page.on('console', msg => {
    const text = msg.text();
    if (text.includes('[PERF]')) {
      metrics.performanceLogs.push({
        type: msg.type(),
        text: text,
        timestamp: Date.now()
      });
    }
    metrics.consoleLogs.push({
      type: msg.type(),
      text: text
    });
  });

  // Capture network requests
  await page.setRequestInterception(true);
  const apiCallsMap = new Map();
  
  page.on('request', request => {
    if (request.url().includes('/api/')) {
      apiCallsMap.set(request.url(), {
        url: request.url(),
        method: request.method(),
        startTime: Date.now()
      });
    }
    request.continue();
  });

  page.on('response', response => {
    if (response.url().includes('/api/')) {
      const requestData = apiCallsMap.get(response.url());
      if (requestData) {
        metrics.apiCalls.push({
          url: response.url().replace('http://localhost:3002', ''),
          method: requestData.method,
          status: response.status(),
          duration: Date.now() - requestData.startTime,
          size: parseInt(response.headers()['content-length'] || '0')
        });
      }
    }
  });

  // Navigate and measure
  const startTime = Date.now();
  await page.goto(url, { waitUntil: 'networkidle0', timeout: 60000 });
  
  // Get performance metrics
  const perfData = await page.evaluate(() => {
    const perfEntries = performance.getEntriesByType('navigation')[0];
    const paintEntries = performance.getEntriesByType('paint');
    const fcpEntry = paintEntries.find(entry => entry.name === 'first-contentful-paint');
    
    return {
      navigationStart: perfEntries.fetchStart,
      domContentLoaded: perfEntries.domContentLoadedEventEnd - perfEntries.fetchStart,
      loadComplete: perfEntries.loadEventEnd - perfEntries.fetchStart,
      fcp: fcpEntry ? fcpEntry.startTime : 0
    };
  });

  metrics.navigationStart = startTime;
  metrics.fcp = Math.round(perfData.fcp);
  metrics.domContentLoaded = Math.round(perfData.domContentLoaded);
  metrics.loadComplete = Math.round(perfData.loadComplete);

  // Wait a bit for any async operations
  await page.waitForTimeout(2000);

  await page.close();
  return metrics;
}

// Run if called directly
if (require.main === module) {
  collectPerformanceMetrics().catch(console.error);
}

module.exports = { collectPerformanceMetrics };