/**
 * Geometric evidence: saved tunnel centerline versus saved tile-allocation
 * bounding boxes. AABB contact is never proof of a clear, connected passage.
 * Endpoint/boundary touches count as contacts, deliberately labeled as such.
 */

function validFootprint(piece) {
  return piece && [piece.x,piece.y,piece.z,piece.width,piece.depth,piece.height]
    .every(Number.isFinite) && piece.width > 0 && piece.depth > 0 && piece.height > 0;
}

/** Slab clipping: line segment touches a recorded XY or XYZ AABB. */
export function segmentTouchesFootprint(a,b,piece,spatial=true) {
  if (!validFootprint(piece) || !Array.isArray(a) || !Array.isArray(b)
    || a.length !== 3 || b.length !== 3
    || ![...a,...b].every(Number.isFinite)) return false;
  const lows=[piece.x,piece.y,piece.z];
  const highs=[piece.x+piece.width,piece.y+piece.depth,piece.z+piece.height];
  let enter=0, exit=1;
  for(let i=0;i<(spatial?3:2);i++){
    const delta=b[i]-a[i];
    if(delta===0){
      if(a[i]<lows[i] || a[i]>highs[i])return false;
      continue;
    }
    const t0=(lows[i]-a[i])/delta, t1=(highs[i]-a[i])/delta;
    enter=Math.max(enter,Math.min(t0,t1));
    exit=Math.min(exit,Math.max(t0,t1));
    if(enter>exit)return false;
  }
  return true;
}

/**
 * Classify saved footprints and distinct logical placements for one line.
 * A placement contacted in XYZ must not also count as XY-only because one of
 * its other saved fragments intersects only the top-down projection.
 */
export function analyzeTunnelPlacementContacts(tunnel, footprints=[], caveGroups=[],
  pocketGroups=[]) {
  const xyzIndices=[],xyOnlyIndices=[];
  const pointList=tunnel?.points;
  if(!Array.isArray(pointList) || pointList.length<2) {
    return {xyzIndices,xyOnlyIndices,xyzPlacements:[],xyOnlyPlacements:[]};
  }
  const identity=new Map();
  for(const group of caveGroups){
    for(const index of group.fragments||[])identity.set(index,{
      key:"cave:"+group.id,label:"Cave group G"+group.id,
    });
  }
  for(const group of pocketGroups){
    for(const index of group.fragments||[])identity.set(index,{
      key:"pocket-group:"+group.id,
      label:group.asset?.name || "Pocket placement PG"+group.id,
    });
  }
  const placements=new Map();
  for(const [index,piece] of footprints.entries()){
    if(!validFootprint(piece))continue;
    let xyz=false,xy=false;
    for(let j=1;j<pointList.length;j++){
      const a=pointList[j-1],b=pointList[j];
      if(!segmentTouchesFootprint(a,b,piece,false))continue;
      xy=true;
      if(segmentTouchesFootprint(a,b,piece,true)){xyz=true;break;}
    }
    if(!xy)continue;
    if(xyz)xyzIndices.push(index);else xyOnlyIndices.push(index);
    const id=identity.get(index)||{
      key:piece.kind+":"+index,
      label:(piece.asset?.name || "Unidentified "+piece.kind+" tile #"+piece.tileIndex),
    };
    const current=placements.get(id.key);
    if(!current || (xyz && !current.xyz)){
      placements.set(id.key,{label:id.label,xyz});
    }
  }
  const xyzPlacements=[],xyOnlyPlacements=[];
  for(const item of placements.values()) {
    (item.xyz?xyzPlacements:xyOnlyPlacements).push(item.label);
  }
  return {xyzIndices,xyOnlyIndices,xyzPlacements,xyOnlyPlacements};
}
