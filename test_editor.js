const { chromium } = require('playwright');
(async () => {
    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    await page.goto('http://localhost:8080');

    // Wait for editor
    await page.waitForSelector('.page-editor');

    // Click editor
    await page.click('.page-editor');

    // Type Line A
    await page.keyboard.type('Line A');

    // Press Enter
    await page.keyboard.press('Enter');

    // Type Line B
    await page.keyboard.type('Line B');

    // Evaluate DOM
    const result = await page.evaluate(() => {
        const ed = document.querySelector('.page-editor');
        const range = document.createRange();
        range.selectNodeContents(ed);
        return {
            innerHTML: ed.innerHTML,
            outerHTML: ed.outerHTML,
            textContent: ed.textContent,
            rangeText: range.toString(),
            nodes: Array.from(ed.childNodes).map(n => ({
                nodeName: n.nodeName,
                nodeType: n.nodeType,
                text: n.nodeValue
            }))
        };
    });

    console.log(JSON.stringify(result, null, 2));

    await browser.close();
})();
