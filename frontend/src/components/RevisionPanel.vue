<script setup lang="ts">
import {ref,computed,watch} from 'vue';
import type {Dataset,RevisionPreview,RevisionTrail} from '../types/domain';
import {previewRevision,confirmRevision,getRevisions} from '../api/datasets';
import type {RevisionPayload,CorrectionInput} from '../api/datasets';
import {useTask} from '../hooks/useTask';
import ErrorNotice from './common/ErrorNotice.vue';
import {number,date} from '../utils/format';
const props=defineProps<{datasets:Dataset[];modelValue:number}>();
const emit=defineEmits(['update:modelValue','revised']);
const reason=ref(''),rawText=ref(''),preview=ref<RevisionPreview|null>(null),history=ref<RevisionTrail[]>([]),notice=ref('');
const {busy,error,perform}=useTask();
const current=computed(()=>props.datasets.find(d=>d.id===props.modelValue)||null);
const payloadBase=computed(()=>current.value?.version||1);
function parseCorrections():CorrectionInput[]{
  const items:CorrectionInput[]=[];
  const seen=new Set<string>();
  for(const line of rawText.value.split(/\r?\n/)){
    const text=line.trim();
    if(!text)continue;
    const parts=text.split(',').map(p=>p.trim());
    if(parts.length!==3)throw new Error(`行“${text}”格式不正确，应为：试片编号,参考X改值,候选Y改值`);
    const [code,refText,candText]=parts;
    if(!code)throw new Error(`行“${text}”缺少试片编号`);
    if(seen.has(code))throw new Error(`试片 ${code} 在清单中重复，请合并为一行`);
    seen.add(code);
    const parse=(v:string,label:string)=>{
      if(v===''||v==='-'||v==='—')return null;
      const n=Number(v);
      if(!Number.isFinite(n)||n<0||n>100)throw new Error(`试片 ${code} 的${label}改值“${v}”非法（需为0–100的有限数，留空表示不改）`);
      return n;
    };
    items.push({sample_code:code,reference_value:parse(refText,'参考X'),candidate_value:parse(candText,'候选Y')});
  }
  if(!items.length)throw new Error('请至少填写一条试片更正');
  return items;
}
function buildPayload():RevisionPayload{
  return {base_version:payloadBase.value,reason:reason.value.trim(),corrections:parseCorrections()};
}
async function loadHistory(){
  if(!current.value){history.value=[];return;}
  history.value=await getRevisions(current.value.id);
}
watch(()=>props.modelValue,()=>{preview.value=null;notice.value='';rawText.value='';reason.value='';perform(loadHistory);},{immediate:false});
function doPreview(){
  preview.value=null;notice.value='';
  perform(async()=>{
    if(reason.value.trim().length<5)throw new Error('请填写至少5个字的更正原因，供后续追查');
    preview.value=await previewRevision(props.modelValue,buildPayload());
  });
}
function doConfirm(){
  perform(async()=>{
    const payload=buildPayload();
    const result=await confirmRevision(props.modelValue,payload);
    notice.value=result.idempotent_hit
      ?`该更正此前已确认过（重复提交不多建版本），仍指向修订版 #${result.new_dataset_id}。`
      :`已生成完整修订版“${result.new_name}”（v${result.version}），共更正 ${result.change_count} 片，其余试片照原样保留。`;
    preview.value=null;rawText.value='';reason.value='';
    await emit('revised',result.new_dataset_id);
    await loadHistory();
  });
}
function reset(){preview.value=null;notice.value='';}
defineExpose({refresh:()=>perform(loadHistory)});
perform(loadHistory);
</script>
<template>
  <section class="revision-panel">
    <div class="section-heading">
      <h2>读数更正与修订版</h2>
      <span v-if="current">CURRENT VERSION / v{{current.version}}</span>
    </div>
    <ErrorNotice :message="error" @retry="perform(loadHistory)"/>
    <div v-if="current?.has_successor" class="revision-banner">本版已生成后继修订版；同一版仅接纳一个后继版本，新的更正请在最新修订版上提交。</div>
    <p v-if="current" class="muted">
      选定原样本集 <b>「{{current.name}}」</b>（v{{current.version}}，{{current.row_count}}对）。
      更正会生成一份可供新研究使用的<b>完整修订版</b>：未改试片照原样保留；旧研究与资格档案仍按原始读数复算，不受影响。
    </p>
    <form class="revision-form" @submit.prevent="doPreview">
      <label>更正原因（将随修订前后值一并留痕）
        <textarea v-model="reason" rows="2" minlength="5" maxlength="600" placeholder="例如：纸质记录复核发现 CG1-024 候选侧抄录错位，按原始记录单更正"></textarea>
      </label>
      <label>改值清单（每行一片：试片编号,参考X改值,候选Y改值；留空或“-”表示该侧不改）
        <textarea v-model="rawText" rows="4" placeholder="CG1-024,-,52.3&#10;CG1-031,41.05,-"></textarea>
      </label>
      <div class="revision-actions">
        <button class="primary" type="submit" :disabled="busy">核对差异 →</button>
        <button v-if="preview" class="outline" type="button" @click="reset">放弃核对</button>
      </div>
    </form>
    <div v-if="preview" class="diff-card">
      <h3>差异核对（基于 v{{preview.base_version}}）</h3>
      <p class="muted">命中 {{preview.change_count}} 片实际改动{{preview.noop_count?`，另有 ${preview.noop_count} 片与原值相同已忽略`:''}}；全集 {{preview.row_count}} 对将整体复制到修订版。</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>试片编号</th><th>参考 X 前 → 后</th><th>候选 Y 前 → 后</th></tr></thead>
          <tbody>
            <tr v-for="c in preview.changes" :key="c.sample_code">
              <td><b>{{c.sample_code}}</b></td>
              <td><span :class="{changed:c.reference_before!==c.reference_after}">{{number(c.reference_before,4)}} → {{number(c.reference_after,4)}}</span></td>
              <td><span :class="{changed:c.candidate_before!==c.candidate_after}">{{number(c.candidate_before,4)}} → {{number(c.candidate_after,4)}}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="revision-actions">
        <button class="primary" :disabled="busy" @click="doConfirm">确认无误，生成修订版 →</button>
        <button class="outline" :disabled="busy" @click="reset">返回修改</button>
      </div>
      <p class="muted">指纹 {{preview.correction_hash.slice(0,16)}}…：相同原因与改值重复确认不会多建版本。</p>
    </div>
    <p v-if="notice" class="success" role="status">{{notice}}</p>
    <div class="revision-history">
      <h3>修订留痕</h3>
      <p v-if="!history.length" class="muted">该样本集尚无修订记录。原始读数一经导入即冻结，所有更正均以新版本交付。</p>
      <article v-for="rev in history" :key="rev.id">
        <header>
          <b>v{{rev.base_version}} → v{{rev.version}}</b>
          <span>{{rev.new_name}}</span>
          <small>{{date(rev.created_at)}} · {{rev.created_by}}</small>
        </header>
        <p class="muted">原因：{{rev.reason}}</p>
        <div class="table-wrap">
          <table>
            <thead><tr><th>试片</th><th>参考 X 前 → 后</th><th>候选 Y 前 → 后</th></tr></thead>
            <tbody>
              <tr v-for="c in rev.corrections" :key="c.sample_code">
                <td>{{c.sample_code}}</td>
                <td><span class="changed">{{number(c.reference_before,4)}} → {{number(c.reference_after,4)}}</span></td>
                <td><span class="changed">{{number(c.candidate_before,4)}} → {{number(c.candidate_after,4)}}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <button class="text-button" @click="emit('update:modelValue',rev.new_dataset_id)">打开该修订版 ↗</button>
      </article>
    </div>
  </section>
</template>
