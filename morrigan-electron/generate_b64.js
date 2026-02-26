const sharp = require('sharp');
const fs = require('fs');
const path = require('path');

const svg = '<svg width="32" height="32" xmlns="http://www.w3.org/2000/svg"><rect width="32" height="32" fill="#7c3aed" rx="4" ry="4"/><text x="16" y="24" font-family="sans-serif" font-size="20" font-weight="bold" fill="white" text-anchor="middle">M</text></svg>';

sharp(Buffer.from(svg)).png().toBuffer().then(b => {
    const code = `export const iconBase64 = '${b.toString('base64')}';\n`;
    fs.writeFileSync(path.join(__dirname, 'src', 'main', 'icon-base64.ts'), code);
    console.log('generated src/main/icon-base64.ts');
}).catch(console.error);
