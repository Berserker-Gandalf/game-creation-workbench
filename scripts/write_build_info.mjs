import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';

const files = {};
function collect(folder) {
  for (const entry of fs.readdirSync(folder, { withFileTypes: true })) {
    const file = path.join(folder, entry.name);
    if (entry.isDirectory()) collect(file);
    else if (entry.isFile() && entry.name !== 'workbench-build.json') files[path.relative('dist', file).replaceAll('\\', '/')] = createHash('sha256').update(fs.readFileSync(file)).digest('hex');
  }
}
collect('dist');
fs.writeFileSync('dist/workbench-build.json', JSON.stringify({ format: 1, version: JSON.parse(fs.readFileSync('package.json', 'utf8')).version, files }, null, 2) + '\n');
