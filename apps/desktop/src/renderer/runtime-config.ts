import type {Json} from '../core.ts';

export const LOW_RESOURCE_PRESET='LowResource';

export function defaultRuntimeConfig():Json{
 return {
  preset:LOW_RESOURCE_PRESET,
  dataset:'generic',dataset_root:'',sequence:'',
  pipeline:{semantic:{mode:'ground_truth'},ground:{enabled:true,parameter_overrides:{min_range:0,max_range:100}},terrain:{enabled:true},temporal:{enabled:false}},
  map:{policy:'distance_lod',resource_profile:'performance',governor_override:'automatic'},
  playback:{fps:10,speed:1,frame_limit:30,full_sequence:false},
  visualization:{point_budget:15000,cell_budget:10000,update_hz:2,max_in_flight:1},
 };
}

export function fullSequenceConfig(current:Json):Json{
 return {...current,playback:{...(current.playback??{}),full_sequence:true}};
}
