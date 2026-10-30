import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { COPY, REPO, RELEASES, SCREENS, loadRelease, resolveDownloads, screenshot } from '../docs/site/main.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures/website-release-legacy.json'), 'utf8'));

test('current download metadata can advance without changing legacy regression fixtures', () => {
  const current = JSON.parse(fs.readFileSync(path.join(root, 'docs/site/release.json'), 'utf8'));
  const value = resolveDownloads(current);
  assert.ok(value);
  assert.equal(value.tag, current.tag);
  assert.deepEqual(Object.keys(value.items), ['installer','portable','source']);
  for (const asset of Object.values(value.items)) {
    assert.equal(asset.checksum, asset.url + '.sha256');
    assert.ok(asset.url.startsWith(REPO + '/releases/download/' + current.tag + '/'));
  }
});

test('release loading uses a same-site request without account credentials', async () => {
  const value = await loadRelease('https://example.com/site/release.json', async (url, options) => {
    assert.equal(url, 'https://example.com/site/release.json');
    assert.equal(options.credentials, 'omit');
    assert.equal(options.cache, 'no-cache');
    assert.ok(options.signal instanceof AbortSignal);
    return {ok:true, json:async () => manifest};
  });
  assert.equal(value, manifest);
});

test('HTTP failures and unreadable release metadata reach the fallback path', async () => {
  await assert.rejects(loadRelease('release.json', async () => ({ok:false})), /Release metadata unavailable/);
  await assert.rejects(loadRelease('release.json', async () => ({ok:true,json:async () => { throw new SyntaxError('Invalid JSON'); }})), SyntaxError);
});

test('slow requests and slow response bodies are aborted within the configured budget', async () => {
  for (const slowBody of [false,true]) {
    await assert.rejects(loadRelease('release.json', async (_url, {signal}) => {
      const pending = () => new Promise((_resolve,reject) => signal.addEventListener('abort', () => reject(signal.reason), {once:true}));
      return slowBody ? {ok:true,json:pending} : pending();
    }, 20), {name:'AbortError'});
  }
});

test('published preview exposes the three real asset types and paired checksums', () => {
  const value = resolveDownloads(manifest);
  assert.equal(value.tag, 'v0.19.0');
  assert.equal(value.prerelease, true);
  assert.deepEqual(Object.keys(value.items), ['installer','portable','source']);
  for (const asset of Object.values(value.items)) {
    assert.ok(asset.url.startsWith(REPO + '/releases/download/v0.19.0/'));
    assert.equal(asset.checksum, asset.url + '.sha256');
    assert.ok(asset.size > 0);
  }
});

test('unpublished, invalid and incomplete metadata never fabricate download links', () => {
  for (const value of [null, {}, {...manifest,published:false}, {...manifest,tag:'../../elsewhere'}, {...manifest,releaseUrl:'https://example.com/'}]) assert.equal(resolveDownloads(value), null);
  const partial = resolveDownloads({...manifest,assets:manifest.assets.filter(a => a.name.startsWith('game-creation-'))});
  assert.deepEqual(Object.keys(partial.items), ['source']);
  assert.equal(partial.items.installer, undefined);
  const noChecksums = resolveDownloads({...manifest,assets:manifest.assets.filter(a => !a.name.endsWith('.sha256'))});
  assert.equal(noChecksums.items.installer.checksum, null);
  assert.equal(RELEASES, REPO + '/releases');
});

test('new-brand releases resolve independently and cannot rewrite the existing legacy download', () => {
  const updated = {...manifest,appName:'Questweft',tag:'v0.19.1',releaseUrl:RELEASES+'/tag/v0.19.1',assets:manifest.assets.map(asset=>({...asset,name:asset.name.replaceAll('ZAOWU','Questweft').replaceAll('0.19.0','0.19.1'),url:asset.url.replaceAll('ZAOWU','Questweft').replaceAll('0.19.0','0.19.1')}))};
  const value = resolveDownloads(updated);
  assert.equal(value.appName,'Questweft');
  assert.ok(value.items.installer.url.endsWith('/Questweft-0.19.1-windows-x64-setup.exe'));
  assert.ok(resolveDownloads(manifest).items.installer.url.endsWith('/ZAOWU-0.19.0-windows-x64-setup.exe'));
  const legacy = {...manifest}; delete legacy.appName;
  assert.equal(resolveDownloads(legacy).appName,'ZAOWU');
  for (const appName of ['',null,'Other','../Questweft']) assert.equal(resolveDownloads({...updated,appName}),null);
  assert.equal(resolveDownloads({...updated,assets:manifest.assets}).items.installer,undefined);
});

test('the static homepage exposes the new brand and search content without JavaScript', () => {
  const html = fs.readFileSync(path.join(root,'docs/index.html'),'utf8');
  assert.match(html,/<title>[^<]*游织工坊 Questweft[^<]*AI 独立游戏制作/);
  assert.match(html,/<h1>[\s\S]*?AI 独立游戏制作，[\s\S]*?<\/h1>/);
  assert.ok(!html.includes('造物间'));
  const schema = JSON.parse(html.match(/<script id="software-schema" type="application\/ld\+json">([\s\S]*?)<\/script>/)[1]);
  assert.equal(schema['@type'],'SoftwareApplication');
  assert.equal(schema.name,'游织工坊 Questweft');
  assert.equal(schema.softwareVersion,JSON.parse(fs.readFileSync(path.join(root,'package.json'),'utf8')).version);
  assert.equal(schema.url,html.match(/rel="canonical" href="([^"]+)"/)[1]);
  assert.equal(schema.aggregateRating,undefined);
  assert.ok(fs.readFileSync(path.join(root,'docs/sitemap.xml'),'utf8').includes('<loc>'+schema.url+'</loc>'));
});

test('unexpected hosts, paths and non-files are rejected without affecting valid assets', () => {
  for (const url of ['javascript:alert(1)','https://example.com/app.exe',manifest.assets[0].url + '?redirect=1',manifest.assets[0].url.replace('/download/','/latest/download/')]) {
    const value = resolveDownloads({...manifest,assets:manifest.assets.map((a, i) => i === 0 ? {...a,url} : a)});
    assert.equal(value.items.installer, undefined);
    assert.ok(value.items.portable);
  }
  const invalidSize = resolveDownloads({...manifest,assets:manifest.assets.map((a, i) => i === 0 ? {...a,size:0} : a)});
  assert.equal(invalidSize.items.installer, undefined);
});

test('static references and screenshots work under a GitHub Pages project subpath', () => {
  const html = fs.readFileSync(path.join(root, 'docs/index.html'), 'utf8');
  for (const [, reference] of html.matchAll(/(?:href|src)="([^"]+)"/g)) {
    if (/^(https?:|#)/.test(reference)) continue;
    const url = new URL(reference, 'https://example.com/game-creation-workbench/');
    assert.ok(url.pathname.startsWith('/game-creation-workbench/'), reference);
    assert.ok(fs.statSync(path.join(root, 'docs', reference)).isFile(), reference);
  }
  for (const language of ['zh','en']) for (const view of Object.keys(SCREENS)) assert.ok(fs.statSync(path.join(root, 'docs', screenshot(view,language))).isFile());
  assert.ok(fs.existsSync(path.join(root, 'docs/.nojekyll')));
  assert.equal(fs.readFileSync(path.join(root,'docs/site/mark.svg'),'utf8').replaceAll('\r\n','\n'), fs.readFileSync(path.join(root,'public/brand/mark.svg'),'utf8').replaceAll('\r\n','\n'));
});

test('both galleries reference real bilingual screens with consistent dimensions and separate targets', () => {
  const html = fs.readFileSync(path.join(root, 'docs/index.html'), 'utf8');
  assert.deepEqual(Object.keys(SCREENS), ['workspace','design','tasks','music','modeling','hardware']);
  for (const [view, metadata] of Object.entries(SCREENS)) {
    for (const key of Object.values(metadata)) assert.ok(COPY[key], key);
    assert.ok(html.includes(`id="tab-${view}"`));
    for (const language of ['zh','en']) {
      const file = path.join(root, 'docs', screenshot(view,language));
      assert.ok(fs.statSync(file).isFile());
      if (['design','tasks','music','modeling'].includes(view)) {
        const bytes = fs.readFileSync(file);
        assert.equal(bytes.subarray(1,4).toString(), 'PNG');
        assert.deepEqual([bytes.readUInt32BE(16),bytes.readUInt32BE(20)], [1280,720]);
      }
    }
  }
  for (const view of ['workspace','tasks','music','modeling']) {
    assert.ok(html.includes(`id="hero-tab-${view}"`));
    for (const language of ['zh','en']) {
      const bytes = fs.readFileSync(path.join(root, `docs/site/screens/thumb-${view}-${language}.png`));
      assert.deepEqual([bytes.readUInt32BE(16),bytes.readUInt32BE(20)], [320,180]);
    }
  }
  assert.equal([...html.matchAll(/aria-controls="hero-panel"/g)].length, 4);
  assert.equal([...html.matchAll(/aria-controls="preview-panel"/g)].length, 6);
  assert.notEqual(screenshot('tasks','zh'), screenshot('tasks','en'));
});

test('every interface key has Chinese and English text and each local anchor has a target', () => {
  const html = fs.readFileSync(path.join(root, 'docs/index.html'), 'utf8');
  for (const [, key] of html.matchAll(/data-copy="([^"]+)"/g)) assert.ok(COPY[key], key);
  for (const [key, pair] of Object.entries(COPY)) {
    assert.equal(pair.length, 2, key);
    assert.ok(pair.every(value => typeof value === 'string' && value.trim()), key);
    assert.ok(!/[\u3400-\u9fff]/.test(pair[1]), key);
  }
  const ids = [...html.matchAll(/\sid="([^"]+)"/g)].map(m => m[1]);
  assert.equal(new Set(ids).size, ids.length);
  for (const [, target] of html.matchAll(/href="#([^"]+)"/g)) assert.ok(ids.includes(target), target);
  assert.ok(!html.includes('http://127.0.0.1'));
});

test('sharing cards and generated icons have valid dimensions and project URLs', () => {
  const pngSize = relative => {
    const bytes = fs.readFileSync(path.join(root, 'docs', relative));
    assert.equal(bytes.subarray(1, 4).toString(), 'PNG');
    return [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
  };
  for (const size of [16,32,96]) assert.deepEqual(pngSize(`site/icons/favicon-${size}x${size}.png`), [size,size]);
  for (const [name,size] of [['apple-touch-icon',180],['android-chrome-192x192',192],['android-chrome-512x512',512]]) assert.deepEqual(pngSize(`site/icons/${name}.png`), [size,size]);
  const ico = fs.readFileSync(path.join(root, 'docs/site/icons/favicon.ico'));
  assert.equal(ico.readUInt16LE(2), 1);
  assert.equal(ico.readUInt16LE(4), 3);
  assert.deepEqual([0,1,2].map(i => ico[6+i*16]), [16,32,48]);
  assert.deepEqual(pngSize('site/social/og-image.png'), [1200,630]);
  assert.deepEqual(pngSize('site/social/twitter-image.png'), [1200,675]);
  const html = fs.readFileSync(path.join(root, 'docs/index.html'), 'utf8');
  for (const [,value] of html.matchAll(/(?:property="og:image"|name="twitter:image") content="([^"]+)"/g)) {
    const url = new URL(value);
    assert.equal(url.origin, 'https://berserker-gandalf.github.io');
    assert.ok(url.pathname.startsWith('/game-creation-workbench/site/social/'));
    assert.ok(fs.existsSync(path.join(root, 'docs', url.pathname.replace('/game-creation-workbench/',''))));
  }
});

test('case video stays outside the Pages source and has no website player or entry point', () => {
  const html = fs.readFileSync(path.join(root, 'docs/index.html'), 'utf8');
  assert.ok(!/<video\b|case-video\.html|beacon-route/i.test(html));
  assert.ok(!fs.existsSync(path.join(root, 'docs/case-video.html')));
  for (const name of ['beacon-route-case-zh.mp4','beacon-route-case-zh.srt','beacon-route-voice-preview.mp3','beacon-route-case.png','beacon-route-delivery.png','beacon-route-gameplay.gif','beacon-route-snapshot.png']) {
    assert.ok(fs.existsSync(path.join(root, 'media/case-study', name)));
    assert.ok(!fs.existsSync(path.join(root, 'docs/media', name)));
  }
});
