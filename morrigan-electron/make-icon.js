const sharp = require('sharp');
const fs = require('fs');
const path = require('path');

const svg = `<svg width="32" height="32" xmlns="http://www.w3.org/2000/svg">
  <rect width="32" height="32" fill="#7c3aed" rx="4" ry="4"/>
  <text x="16" y="24" font-family="Arial, sans-serif" font-size="20" font-weight="bold" fill="white" text-anchor="middle">M</text>
</svg>`;

const outPath = path.join(__dirname, 'src', 'main', 'assets', 'm-icon.png');

if (!fs.existsSync(path.dirname(outPath))) {
    fs.mkdirSync(path.dirname(outPath), { recursive: true });
}

sharp(Buffer.from(svg))
    .png()
    .toFile(outPath)
    .then(() => {
        console.log('Icono M generado correctamente en', outPath);
    })
    .catch(err => {
        console.error('Error al generar:', err);
    });
