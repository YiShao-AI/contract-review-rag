const { test, expect } = require('@playwright/test');
const AxeBuilder = require('@axe-core/playwright').default;

test('saved answer supports keyboard source preview and precise evidence', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.chatitem')).toHaveCount(6);

  await page.locator('.chatitem').nth(1).click();
  const citation = page.locator('.citemark').first();
  await expect(citation).toBeVisible();

  await citation.focus();
  await expect(page.locator('#tip')).toHaveClass(/show/);
  await expect(page.locator('#tip')).toContainText('15.5% of Kiosk Transaction Fees');
  await expect(page.locator('#tip')).toHaveCSS('overflow-y', 'auto');

  await citation.press('Enter');
  await expect(page.locator('#drawer')).toHaveClass(/open/);
  await expect(page.locator('#drTitle')).toContainText('Mount Pleasant Laundry');
  await expect(page.locator('#drBody mark')).toHaveCount(1);
  await expect(page.locator('#drBody mark')).toHaveText('15.5% of Kiosk Transaction Fees');
  await expect(page.locator('#drBody .seg-target')).toContainText(
    'rent for the Leased Space will equal 15.5%'
  );

  await page.keyboard.press('Escape');
  await expect(page.locator('#drawer')).not.toHaveClass(/open/);
});

test('static demo has no automatically detectable WCAG A/AA violations', async ({ page }) => {
  await page.goto('/');
  await page.locator('.chatitem').nth(1).click();
  await page.locator('.citemark').first().press('Enter');

  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
  expect(results.violations).toEqual([]);
});
