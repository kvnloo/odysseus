// Live Odysseus Calendar form geometry, exercised in Chromium and WebKit.
// WebKit emulation is NOT native iOS Safari: software-keyboard appearance,
// viewport resize, and OS Dynamic Type still require physical-device checks.
const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');

async function openCreateForm(page) {
  const response = await page.goto('/', { waitUntil: 'domcontentloaded' });
  expect(response && response.ok(), 'The isolated Odysseus app must load').toBeTruthy();

  const rail = page.locator('#rail-calendar:visible');
  if (await rail.count()) {
    await rail.first().click();
  } else {
    await page.locator('#hamburger-btn:visible').click();
    const sidebar = page.locator('#sidebar:not(.hidden)');
    await expect(sidebar).toBeVisible();
    await sidebar.locator('#tool-calendar-btn').click();
  }

  await expect(page.locator('#cal-add')).toBeVisible();
  await page.locator('#cal-add').click();
  const title = page.locator('#cal-f-sum');
  await expect(title).toBeVisible();
  await title.fill('Calendar mobile layout check');
  await expect(page.locator('.cal-form-bespoke')).toHaveClass(/is-expanded/);
  await expect(page.locator('#cal-form-details')).toBeVisible();
}

async function expectRowsInsideContainers(page, label) {
  const geometry = await page.evaluate(() => {
    const details = document.getElementById('cal-form-details');
    const actions = document.querySelector('.cal-form-actions');
    const dateRow = document.getElementById('cal-f-date')?.parentElement;
    const timeRow = document.getElementById('cal-time-row');
    if (!details || !actions || !dateRow || !timeRow) return null;

    const boxes = [
      ['start date', document.getElementById('cal-f-date'), details],
      ['end date', document.getElementById('cal-f-date-end'), details],
      ['all day', document.querySelector('.cal-allday-ctrl'), details],
      ['location', document.getElementById('cal-f-loc'), details],
      ['cancel', document.getElementById('cal-f-cancel'), actions],
      ['save', document.getElementById('cal-f-save'), actions],
    ];
    if (getComputedStyle(timeRow).display !== 'none') {
      boxes.push(['start time', document.getElementById('cal-f-start'), details]);
      boxes.push(['end time', document.getElementById('cal-f-end'), details]);
    }

    const clipped = [];
    for (const [name, element, container] of boxes) {
      if (!element) {
        clipped.push(name + ': missing');
        continue;
      }
      const rect = element.getBoundingClientRect();
      const bounds = container.getBoundingClientRect();
      if (rect.width < 1 || rect.left < bounds.left - 2 || rect.right > bounds.right + 2) {
        clipped.push(name + ': ' + Math.round(rect.left) + '..' +
          Math.round(rect.right) + ' outside ' + Math.round(bounds.left) +
          '..' + Math.round(bounds.right));
      }
    }

    return {
      clipped,
      dateRowOverflow: dateRow.scrollWidth - dateRow.clientWidth,
      detailsOverflow: details.scrollWidth - details.clientWidth,
      actionsOverflow: actions.scrollWidth - actions.clientWidth,
      detailsScrollLeft: details.scrollLeft,
    };
  });

  expect(geometry, label + ': rendered form geometry').not.toBeNull();
  expect(geometry.clipped, label + ': clipped native fields/actions').toEqual([]);
  expect(geometry.dateRowOverflow, label + ': date row horizontal overflow').toBeLessThanOrEqual(2);
  expect(geometry.detailsOverflow, label + ': details horizontal overflow').toBeLessThanOrEqual(2);
  expect(geometry.actionsOverflow, label + ': action row horizontal overflow').toBeLessThanOrEqual(2);
  expect(Math.abs(geometry.detailsScrollLeft), label + ': details moved sideways').toBeLessThanOrEqual(2);
}

async function saveScreenshot(page, testInfo, width, name) {
  const directory = testInfo.config.metadata.evidenceDir;
  fs.mkdirSync(directory, { recursive: true });
  await page.screenshot({
    path: path.join(directory, testInfo.project.name + '-calendar-' + width + '-' + name + '.png'),
    animations: 'disabled',
  });
}

for (const width of [320, 390]) {
  test('Calendar fields and actions stay inside the form at ' + width + ' px', async ({ page }, testInfo) => {
    test.skip(
      !['phone-chromium-portrait', 'phone-webkit-portrait'].includes(testInfo.project.name),
      'Only the portrait phone browser profiles exercise this form regression'
    );
    await page.setViewportSize({ width, height: 844 });
    await openCreateForm(page);

    await expectRowsInsideContainers(page, 'default ' + width + 'px');

    // Focus alone is testable here; it does NOT raise the native software keyboard.
    await page.locator('#cal-f-date-end').focus();
    await expect(page.locator('#cal-f-date-end')).toBeFocused();
    await expectRowsInsideContainers(page, 'date focus ' + width + 'px');

    await page.locator('.cal-allday-switch').click();
    await expect(page.locator('#cal-f-allday')).toBeChecked();
    await expect(page.locator('#cal-time-row')).toBeHidden();
    await page.locator('#cal-f-loc').fill('Layout test location');
    await expect(page.locator('#cal-f-loc')).toBeFocused();
    await expectRowsInsideContainers(page, 'text focus and all day ' + width + 'px');
    await saveScreenshot(page, testInfo, width, 'default');

    // Stress the real CSS at reduced effective width, without claiming to
    // emulate Safari's OS-level Larger Text or a live keyboard transition.
    await page.evaluate(() => {
      document.documentElement.style.zoom = '1.25';
      document.documentElement.style.setProperty('-webkit-text-size-adjust', '150%');
      document.documentElement.style.setProperty('text-size-adjust', '150%');
    });
    await expectRowsInsideContainers(page, 'CSS zoom/text adjustment ' + width + 'px');
    await saveScreenshot(page, testInfo, width, 'zoom125-text150');
  });
}
