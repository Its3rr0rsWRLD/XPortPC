/* Offline pipeline builder for RADV null winsys. Usage: pipe <spec>
   spec lines: kind(comp|gfx) ; stage <vert|tesc|tese|geom|frag|comp> <spv path> ;
   bind <set> <binding> <vktype> <count> ; push <bytes> ; vin <loc> <fmt:f|i|u> ; fout <loc> <f|i|u> ; depth 1 */
#include <vulkan/vulkan.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CK(x) do{VkResult r_=(x); if(r_){fprintf(stderr,"FAIL %s = %d\n",#x,r_);return 3;}}while(0)
typedef struct{uint32_t set,binding,type,count;}Bind;
static uint32_t *rd(const char*p,size_t*sz){FILE*f=fopen(p,"rb");if(!f)return 0;fseek(f,0,SEEK_END);*sz=ftell(f);rewind(f);uint32_t*b=malloc(*sz);fread(b,1,*sz,f);fclose(f);return b;}
int main(int argc,char**argv){
 FILE*sp=fopen(argv[1],"r"); if(!sp)return 1;
 char line[1024]; Bind binds[256]; int nb=0; uint32_t push=0; int comp=0;
 struct{VkShaderStageFlagBits st;char path[900];}stg[8]; int mesh=0; int ns=0;
 struct{uint32_t loc;char t;}vin[40]; int nv=0, fo[16]; char fot[16]; int nf=0; int depth=0, rastdisc=0;
 while(fgets(line,sizeof line,sp)){
  char k[32]; char a[900]; unsigned x,y,z,w;
  if(sscanf(line,"stage %31s %899s",k,a)==2){
    VkShaderStageFlagBits s=!strcmp(k,"vert")?VK_SHADER_STAGE_VERTEX_BIT:!strcmp(k,"tesc")?VK_SHADER_STAGE_TESSELLATION_CONTROL_BIT:!strcmp(k,"tese")?VK_SHADER_STAGE_TESSELLATION_EVALUATION_BIT:!strcmp(k,"geom")?VK_SHADER_STAGE_GEOMETRY_BIT:!strcmp(k,"frag")?VK_SHADER_STAGE_FRAGMENT_BIT:!strcmp(k,"mesh")?VK_SHADER_STAGE_MESH_BIT_EXT:!strcmp(k,"task")?VK_SHADER_STAGE_TASK_BIT_EXT:VK_SHADER_STAGE_COMPUTE_BIT;
    if(s==VK_SHADER_STAGE_COMPUTE_BIT)comp=1; if(s==VK_SHADER_STAGE_MESH_BIT_EXT)mesh=1; stg[ns].st=s; strcpy(stg[ns].path,a); ns++;
  } else if(sscanf(line,"bind %u %u %u %u",&x,&y,&z,&w)==4){binds[nb++]=(Bind){x,y,z,w};}
  else if(sscanf(line,"push %u",&x)==1)push=x;
  else if(sscanf(line,"vin %u %31s",&x,k)==2){vin[nv].loc=x;vin[nv].t=k[0];nv++;}
  else if(sscanf(line,"fout %u %31s",&x,k)==2){fo[nf]=x;fot[nf]=k[0];nf++;}
  else if(!strncmp(line,"depth",5))depth=1;
  else if(!strncmp(line,"rastdisc",8))rastdisc=1;
 }
 VkApplicationInfo ai={VK_STRUCTURE_TYPE_APPLICATION_INFO};ai.apiVersion=VK_API_VERSION_1_3;
 VkInstanceCreateInfo ci={VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};ci.pApplicationInfo=&ai;
 VkInstance in; CK(vkCreateInstance(&ci,0,&in));
 uint32_t n=1; VkPhysicalDevice pd; CK(vkEnumeratePhysicalDevices(in,&n,&pd));
 float pr=1; VkDeviceQueueCreateInfo qi={VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};qi.queueCount=1;qi.pQueuePriorities=&pr;
 VkPhysicalDeviceVulkan13Features f13={VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES};f13.dynamicRendering=1;f13.subgroupSizeControl=1;f13.computeFullSubgroups=1;
 VkPhysicalDeviceMeshShaderFeaturesEXT fm={VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MESH_SHADER_FEATURES_EXT};
 VkPhysicalDeviceFeatures2 f2={VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2};f2.pNext=&f13; if(getenv("PIPE_MESH"))f13.pNext=&fm;
 vkGetPhysicalDeviceFeatures2(pd,&f2); f13.dynamicRendering=1;
 const char*mext[1]={VK_EXT_MESH_SHADER_EXTENSION_NAME};
 VkDeviceCreateInfo di={VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO}; if(getenv("PIPE_MESH")){di.enabledExtensionCount=1;di.ppEnabledExtensionNames=mext;}di.pNext=&f2;di.queueCreateInfoCount=1;di.pQueueCreateInfos=&qi;
 VkDevice dev; CK(vkCreateDevice(pd,&di,0,&dev));
 /* layouts */
 uint32_t maxset=0; for(int i=0;i<nb;i++) if(binds[i].set>maxset)maxset=binds[i].set;
 VkDescriptorSetLayout sl[32]; if(maxset>=31)return 4;
 VkShaderStageFlags all=comp?VK_SHADER_STAGE_COMPUTE_BIT:VK_SHADER_STAGE_ALL_GRAPHICS|(mesh?VK_SHADER_STAGE_MESH_BIT_EXT|VK_SHADER_STAGE_TASK_BIT_EXT:0);
 for(uint32_t s=0;s<=maxset;s++){
  VkDescriptorSetLayoutBinding b[128]; int c=0;
  for(int i=0;i<nb;i++) if(binds[i].set==s){b[c]=(VkDescriptorSetLayoutBinding){binds[i].binding,binds[i].type,binds[i].count,all,0};c++;}
  VkDescriptorSetLayoutCreateInfo li={VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};li.bindingCount=c;li.pBindings=b;
  CK(vkCreateDescriptorSetLayout(dev,&li,0,&sl[s]));
 }
 VkPushConstantRange pcr={all,0,push?push:4}; if(push>128)pcr.size=128;
 VkPipelineLayoutCreateInfo pl={VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};pl.setLayoutCount=nb?maxset+1:0;pl.pSetLayouts=sl;
 if(push){pl.pushConstantRangeCount=1;pl.pPushConstantRanges=&pcr;}
 VkPipelineLayout lay; CK(vkCreatePipelineLayout(dev,&pl,0,&lay));
 VkPipelineShaderStageCreateInfo ss[8];
 for(int i=0;i<ns;i++){size_t sz;uint32_t*code=rd(stg[i].path,&sz);if(!code){fprintf(stderr,"cannot read\n");return 5;}
  VkShaderModuleCreateInfo mi={VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};mi.codeSize=sz;mi.pCode=code;
  VkShaderModule m; CK(vkCreateShaderModule(dev,&mi,0,&m));
  ss[i]=(VkPipelineShaderStageCreateInfo){VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO};ss[i].stage=stg[i].st;ss[i].module=m;ss[i].pName="main";}
 VkPipeline pipe;
 if(comp){VkComputePipelineCreateInfo cp={VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO};cp.stage=ss[0];cp.layout=lay;CK(vkCreateComputePipelines(dev,0,1,&cp,0,&pipe));}
 else{
  VkVertexInputBindingDescription vb={0,512,VK_VERTEX_INPUT_RATE_VERTEX}; VkVertexInputAttributeDescription va[40];
  for(int i=0;i<nv;i++){va[i].location=vin[i].loc;va[i].binding=0;va[i].offset=(vin[i].loc%32)*16;va[i].format=vin[i].t=='i'?VK_FORMAT_R32G32B32A32_SINT:vin[i].t=='u'?VK_FORMAT_R32G32B32A32_UINT:VK_FORMAT_R32G32B32A32_SFLOAT;}
  VkPipelineVertexInputStateCreateInfo vi={VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO};vi.vertexBindingDescriptionCount=nv?1:0;vi.pVertexBindingDescriptions=&vb;vi.vertexAttributeDescriptionCount=nv;vi.pVertexAttributeDescriptions=va;
  int tess=0;for(int i=0;i<ns;i++)if(stg[i].st==VK_SHADER_STAGE_TESSELLATION_CONTROL_BIT)tess=1;
  VkPipelineInputAssemblyStateCreateInfo ia={VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO};ia.topology=tess?VK_PRIMITIVE_TOPOLOGY_PATCH_LIST:VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
  VkPipelineTessellationStateCreateInfo ts={VK_STRUCTURE_TYPE_PIPELINE_TESSELLATION_STATE_CREATE_INFO};ts.patchControlPoints=3;
  VkPipelineViewportStateCreateInfo vp={VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO};vp.viewportCount=1;vp.scissorCount=1;
  VkPipelineRasterizationStateCreateInfo rs={VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO};rs.lineWidth=1;rs.rasterizerDiscardEnable=rastdisc;rs.cullMode=VK_CULL_MODE_NONE;
  VkPipelineMultisampleStateCreateInfo ms={VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO};ms.rasterizationSamples=VK_SAMPLE_COUNT_1_BIT;
  VkPipelineDepthStencilStateCreateInfo ds={VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO};ds.depthTestEnable=depth;ds.depthWriteEnable=depth;ds.depthCompareOp=VK_COMPARE_OP_LESS_OR_EQUAL;
  VkPipelineColorBlendAttachmentState ba[8];VkFormat cf[8];int nc=0;for(int i=0;i<nf;i++){if(fo[i]>=nc)nc=fo[i]+1;}if(nc>8)nc=8;
  for(int i=0;i<8;i++){ba[i]=(VkPipelineColorBlendAttachmentState){0};ba[i].colorWriteMask=15;cf[i]=VK_FORMAT_R8G8B8A8_UNORM;}
  for(int i=0;i<nf;i++)if(fo[i]<8){cf[fo[i]]=fot[i]=='i'?VK_FORMAT_R8G8B8A8_SINT:fot[i]=='u'?VK_FORMAT_R8G8B8A8_UINT:VK_FORMAT_R8G8B8A8_UNORM;}
  VkPipelineColorBlendStateCreateInfo cb={VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO};cb.attachmentCount=nc;cb.pAttachments=ba;
  VkDynamicState dyn[2]={VK_DYNAMIC_STATE_VIEWPORT,VK_DYNAMIC_STATE_SCISSOR};VkPipelineDynamicStateCreateInfo dsn={VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO};dsn.dynamicStateCount=2;dsn.pDynamicStates=dyn;
  VkPipelineRenderingCreateInfo ri={VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO};ri.colorAttachmentCount=nc;ri.pColorAttachmentFormats=cf;ri.depthAttachmentFormat=depth?VK_FORMAT_D32_SFLOAT:VK_FORMAT_UNDEFINED;
  VkGraphicsPipelineCreateInfo gp={VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO};gp.pNext=&ri;gp.stageCount=ns;gp.pStages=ss;if(!mesh){gp.pVertexInputState=&vi;gp.pInputAssemblyState=&ia;}if(tess)gp.pTessellationState=&ts;gp.pViewportState=&vp;gp.pRasterizationState=&rs;gp.pMultisampleState=&ms;
  if(!rastdisc){gp.pDepthStencilState=&ds;gp.pColorBlendState=&cb;}gp.pDynamicState=&dsn;gp.layout=lay;
  CK(vkCreateGraphicsPipelines(dev,0,1,&gp,0,&pipe));
 }
 puts("OK");return 0;}
