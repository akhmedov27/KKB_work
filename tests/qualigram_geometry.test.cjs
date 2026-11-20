// Development-only pointer geometry checks; Node is not required on the user's PC.
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context={window:{}};vm.runInNewContext(fs.readFileSync('app/static/qualigram_geometry.js','utf8'),context);
const geometry=context.window.QualigramGeometry,rect={x:200,y:300,width:400,height:160};
const plain=value=>JSON.parse(JSON.stringify(value));
test('resize fixes opposite sides and ignores irrelevant movement',()=>{
 assert.deepEqual(plain(geometry.resize(rect,'e',70,80,1200,1697)),{x:200,y:300,width:470,height:160});
 assert.deepEqual(plain(geometry.resize(rect,'nw',-30,-40,1200,1697)),{x:170,y:260,width:430,height:200});
});
test('all eight handles respect page bounds and minimum size',()=>{
 for(const handle of ['nw','n','ne','e','se','s','sw','w'])for(const d of [-10000,10000]){
  const value=geometry.resize(rect,handle,d,d,1200,1697);
  assert.ok(value.x>=20&&value.y>=140&&value.x+value.width<=1180&&value.y+value.height<=1677);
  assert.ok(value.width>=16&&value.height>=16);
 }
});
test('shift movement preserves exact locked coordinate including fractional values',()=>{
 const fractional={...rect,x:203.4,y:307.8};
 const horizontal=geometry.move(fractional,150,900,1200,1697,'x'),vertical=geometry.move(fractional,900,150,1200,1697,'y');
 assert.equal(horizontal.y,307.8);assert.equal(horizontal.x,350);
 assert.equal(vertical.x,203.4);assert.equal(vertical.y,460);
 assert.deepEqual(plain(geometry.move(rect,-10000,10000,1200,1697)),{x:20,y:1517});
});
