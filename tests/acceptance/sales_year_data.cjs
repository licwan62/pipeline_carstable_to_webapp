// Verify the published annual data with the same pure functions used by the UI.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const args = process.argv.slice(2);
const root = path.resolve(args[args.indexOf('--site') + 1]);
const D = require(path.join(root, 'assets/app/size-evolution-data.js'));
const read = file => JSON.parse(fs.readFileSync(file,'utf8'));
const generated = path.join(root,'data/generated');
const manifest = read(path.join(generated,'sales-year-data.json'));
const match = read(path.join(generated,'size-match-data.json'));
assert.equal(manifest.origin.a0_version,match.origin.a0_version);
let rows = 0, missing = 0;
const snapshots = new Map();
for(const source of match.sources.filter(source=>['US','HNT','TM','TM_拆分'].includes(source.name))) {
  const snapshot = [];
  for(const group of source.make_groups) {
    const full = read(path.join(generated,group.records_path)).records;
    const salesGroup = manifest.make_groups.find(item=>item.kind===group.kind && item.make===group.make);
    assert.ok(salesGroup,`Missing annual shard ${group.make}/${group.kind}`);
    const sales = read(path.join(generated,salesGroup.records_path));
    D.assignRecordKeys(full,source.name);
    const normalized = full.map(record=>D.normalizeRecord(record,{source:source.name}));
    const configs = D.buildConfigurations(normalized);
    const result = D.aggregateSales(configs,sales.records);
    for(const record of full) {
      const id = record.values['DIMENSION-ID'];
      const pairs = sales.records[id];
      assert.ok(pairs,`Missing annual identity ${id}`);
      assert.equal(pairs.reduce((sum,[,value])=>sum+(value??0),0),Number(record.values['尺寸组销量']));
      if(source.name==='US') { rows++; missing+=pairs.filter(([,value])=>value===null).length; }
    }
    snapshot.push([group.kind,group.make,Array.from(result.totals,([year,item])=>[year,item.known,item.missing]).sort((a,b)=>a[0]-b[0])]);
  }
  snapshots.set(source.name,snapshot.sort((a,b)=>JSON.stringify(a).localeCompare(JSON.stringify(b))));
}
for(const source of ['HNT','TM','TM_拆分']) assert.deepEqual(snapshots.get(source),snapshots.get('US'),`US/${source} annual market totals differ`);
assert.equal(rows,manifest.record_count);
console.log(`PASS annual sales: ${rows} dimension identities; ${manifest.atom_count} atoms; ${missing} null values; US and all three stores agree`);
