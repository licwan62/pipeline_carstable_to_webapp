const test = require('node:test');
const assert = require('node:assert/strict');
const D = require('../../site_overrides/assets/app/size-evolution-data.js');

const record = (id) => ({dimensionId:id, intervals:[{startYear:2025,endYear:2027}]});
test('annual sums deduplicate atoms within configurations and visible totals, preserve missing and zero', () => {
  const configs = [{key:'one',records:[record('a'),record('a'),record('b')]},{key:'two',records:[record('a')]}];
  const result = D.aggregateSales(configs,{a:[[2025,7],[2026,0],[2027,null]],b:[[2025,3],[2026,null],[2027,null]]});
  assert.equal(result.groups[0].years.get(2025).known,10);
  assert.equal(result.totals.get(2025).known,10);
  assert.equal(result.groups[1].years.get(2025).known,7);
  assert.equal(result.totals.get(2026).known,0);
  assert.equal(result.totals.get(2026).missing,1);
  assert.equal(result.totals.get(2027).missing,2);
  assert.equal(result.totals.get(2027).atomIds.length,2);
});

test('US/store reuse shards, selected models only, cache and retry failed requests; EU/RU do not fetch', async () => {
  const calls=[];
  let fail=true;
  const load=D.createSalesLoader(async path=>{
    calls.push(path);
    if(path==='data/sales.json') return {format_version:1,origin:{sales_version:'v'},make_groups:[{kind:'nonpick',make:'Test',records_path:'one.json'},{kind:'pick',make:'Test',records_path:'pickup.json'},{kind:'nonpick',make:'Other',records_path:'other.json'}]};
    if(fail){fail=false;throw Error('network');}
    return {kind:'nonpick',make:'Test',models:{One:['a'],Two:['b']},records:{a:[[2025,0]],b:[[2025,9]]}};
  },'data/sales.json');
  const key=source=>D.modelKey(source,'nonpick','Test','One');
  await assert.rejects(load([key('US')]),/network/);
  const us=await load([key('US')]);
  const store=await load([key('HNT')]);
  assert.deepEqual(us,store);
  assert.deepEqual(us.records,{a:[[2025,0]]});
  assert.deepEqual(calls,['data/sales.json','data/one.json','data/one.json']);
  assert.equal((await load([key('EU')])).supported,false);
  assert.equal((await load([key('RU')])).supported,false);
  assert.equal(calls.length,3);
});
