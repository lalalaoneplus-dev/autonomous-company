const fs = require('fs');
const assert = require('assert');
const path = require('path');

const read = (file) => fs.readFileSync(path.join(__dirname, file), 'utf-8');

function runChecks() {
  console.log("Running comprehensive UI defect checks...");

  // 1. Check for real versus paper revenue labels
  const treasuryContent = read('app/treasury/page.tsx');
  assert(treasuryContent.includes('data-testid="paper-revenue-label"'), "Missing paper revenue label test ID");
  assert(treasuryContent.includes('PAPER MODE'), "Missing PAPER MODE indicator");
  assert(treasuryContent.includes('Real Balance (DISABLED)'), "Missing explicit real money disabled text");

  // 2. Check for demo evidence labeling in opportunities
  const oppsContent = read('app/opportunities/page.tsx');
  assert(oppsContent.includes('data-testid="demo-label"'), "Missing demo label element in Opportunities");
  assert(oppsContent.includes('Demo'), "Missing Demo text rendering");
  assert(oppsContent.includes('item.stated_budget_cents / 100'), "Budgets must render from minor currency units");

  // 3. Check for the final OWNER_DELIVERY_DECISION gate in Projects
  const projectsContent = read('app/projects/page.tsx');
  assert(projectsContent.includes('OWNER_DELIVERY_DECISION'), "Projects missing OWNER_DELIVERY_DECISION text constraint");

  // 4. Check for sessionStorage API token enforcement
  const apiContent = read('lib/api.ts');
  assert(!apiContent.includes('"x-owner-token": "demo"'), "x-owner-token demo is still hardcoded!");
  assert(apiContent.includes('sessionStorage.getItem("ownerToken")'), "Missing sessionStorage token extraction");
  assert(apiContent.includes('if (token) headers.set("x-owner-token", token)'), "Stored token must authenticate protected reads");

  // 5. Owner policy controls are editable only through the authenticated PATCH flow
  const settingsContent = read('app/settings/page.tsx');
  assert(settingsContent.includes('Save owner settings'), "Missing owner settings save control");
  assert(settingsContent.includes("'/api/settings'"), "Settings page must call the settings API");
  assert(settingsContent.includes('requireOwner: true'), "Settings updates must require the owner token");
  assert(settingsContent.includes('approval_threshold_cents'), "Missing approval threshold control");

  console.log('✅ UI defect checks passed');
}

try {
  runChecks();
} catch (e) {
  console.error('❌ Test failed:', e.message);
  process.exit(1);
}
