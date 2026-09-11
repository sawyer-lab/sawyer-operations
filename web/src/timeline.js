export function clampRange(start, width, duration) {
  width=Math.min(duration,Math.max(Math.min(.0001,duration),width));
  start=Math.max(0,Math.min(duration-width,start));
  return [start,start+width];
}
export function zoomRange(range,anchor,factor,duration) {
  const width=range[1]-range[0],next=Math.min(duration,Math.max(.0001,width*factor));
  return clampRange(anchor-(anchor-range[0])/width*next,next,duration);
}
export function errorSeries(measured,commands) {
  let index=-1;
  return measured.flatMap(([t,y])=>{
    while(index+1<commands.length&&commands[index+1][0]<=t)index++;
    return index<0?[]:[[t,y-commands[index][1]]];
  });
}
export function visiblePoints(points,range) {
  // Include neighbors so lines crossing the viewport remain visible when zoomed.
  let start=0;while(start<points.length&&points[start][0]<range[0])start++;
  let end=start;while(end<points.length&&points[end][0]<=range[1])end++;
  return points.slice(Math.max(0,start-1),Math.min(points.length,end+1));
}
