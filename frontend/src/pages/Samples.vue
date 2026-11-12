<script setup lang="ts">
import {ref,onMounted,watch} from 'vue';
import {useLab} from '../stores/laboratory';
import {useReadings} from '../stores/readings';
import {useAuth} from '../stores/auth';
import {createInstrument} from '../api/instruments';
import {createDataset} from '../api/datasets';
import {useTask} from '../hooks/useTask';
import PageTitle from '../components/common/PageTitle.vue';
import ErrorNotice from '../components/common/ErrorNotice.vue';
import DatasetSelect from '../components/DatasetSelect.vue';
import RevisionPanel from '../components/RevisionPanel.vue';
import EmptyState from '../components/common/EmptyState.vue';
import {number} from '../utils/format';
const lab=useLab(),reading=useReadings(),auth=useAuth(),selected=ref(0),search=ref(''),offset=ref(0),form=ref(''),showRevision=ref(false);
const {busy,error,perform}=useTask();
const instrument=ref({code:'',name:'',serial:'',lower:0,upper:100});
const dataset=ref({name:'',reference_id:0,candidate_id:0,source_file:'ci-optics-pairs.csv',note:'',csv_text:'sample_code,reference_value,candidate_value\n'});
const currentDataset=ref(0);
async function loadRows(){if(selected.value)await reading.load(selected.value,search.value,offset.value);}
onMounted(()=>perform(async()=>{
  await lab.load();
  selected.value=lab.datasets[0]?.id||0;
  currentDataset.value=selected.value;
  dataset.value.reference_id=lab.instruments[0]?.id||0;
  dataset.value.candidate_id=lab.instruments[1]?.id||0;
  await loadRows();
}));
watch(selected,()=>{offset.value=0;currentDataset.value=selected.value;perform(loadRows);});
watch(currentDataset,id=>{if(id&&id!==selected.value){selected.value=id;}});
function importPairs(){perform(async()=>{const d=await createDataset(dataset.value);await lab.load();selected.value=d.id;form.value='';});}
function addInstrument(){perform(async()=>{await createInstrument(instrument.value);await lab.load();form.value='';});}
function find(){offset.value=0;perform(loadRows);}
async function onRevised(newId:number){
  await lab.load();
  selected.value=newId;
}
</script>
<template>
  <PageTitle index="02" title="同一试片，两侧读数" text="保留仪器编号、配对关系与原始量纲。数据集导入后冻结；读数抄错通过更正生成完整修订版，旧版与旧研究保持原样。">
    <template v-if="auth.canEdit">
      <button class="outline" @click="form=form==='instrument'?'':'instrument'">登记仪器 +</button>
      <button class="outline" @click="form=form==='dataset'?'':'dataset'">导入配对样本 +</button>
      <button class="outline" @click="showRevision=!showRevision">{{showRevision?'收起更正':'读数更正 ↦'}}</button>
    </template>
  </PageTitle>
  <ErrorNotice :message="error" @retry="perform(loadRows)"/>
  <form v-if="form==='instrument'" class="entry-form" @submit.prevent="addInstrument">
    <h2>登记反射率仪</h2>
    <div class="form-grid">
      <label>仪器编号<input v-model="instrument.code" required minlength="2"></label>
      <label>仪器名称<input v-model="instrument.name" required minlength="2"></label>
      <label>序列号<input v-model="instrument.serial" required minlength="2"></label>
      <label>量程下限 %<input type="number" v-model.number="instrument.lower" min="0" max="100"></label>
      <label>量程上限 %<input type="number" v-model.number="instrument.upper" min="0" max="100"></label>
    </div>
    <button class="primary" :disabled="busy">保存仪器登记 →</button>
  </form>
  <form v-if="form==='dataset'" class="entry-form" @submit.prevent="importPairs">
    <h2>导入独立试件的配对读数</h2>
    <div class="form-grid">
      <label>数据集名称<input v-model="dataset.name" required minlength="2"></label>
      <label>参考仪器 X<select v-model="dataset.reference_id"><option v-for="i in lab.instruments" :key="i.id" :value="i.id">{{i.code}}</option></select></label>
      <label>候选仪器 Y<select v-model="dataset.candidate_id"><option v-for="i in lab.instruments" :key="i.id" :value="i.id">{{i.code}}</option></select></label>
    </div>
    <label>观测条件说明<input v-model="dataset.note" maxlength="600"></label>
    <label>来源文件名<input v-model="dataset.source_file" required></label>
    <label>CSV内容<textarea v-model="dataset.csv_text" rows="6" required></textarea></label>
    <p class="muted">20–5000对；sample_code唯一，反射率0–100%，且不得超出登记量程。导入后原始读数不可修改。</p>
    <button class="primary" :disabled="busy">校验并保存样本集 →</button>
  </form>
  <RevisionPanel v-if="showRevision" :datasets="lab.datasets" v-model="currentDataset" @revised="onRevised"/>
  <div class="samples-layout">
    <aside class="instrument-register">
      <p class="eyebrow">INSTRUMENT REGISTER</p>
      <h2>仪器登记簿</h2>
      <article v-for="i in lab.instruments" :key="i.id">
        <span class="instrument-glyph">▣</span>
        <div><b>{{i.code}}</b><h3>{{i.name}}</h3><small>{{i.serial}}</small><p>{{i.lower}}—{{i.upper}}% / {{i.unit}}</p></div>
      </article>
      <p class="muted">参考仪器同样存在测量误差；λ需要来自重复性研究或明确假设。</p>
    </aside>
    <section class="paired-table">
      <div class="data-toolbar">
        <DatasetSelect v-model="selected" :datasets="lab.datasets"/>
        <form @submit.prevent="find"><input v-model="search" aria-label="搜索试片编号" placeholder="试片编号，如 CG1-024"><button class="outline">查找</button></form>
      </div>
      <p class="source-line">
        {{lab.datasets.find(d=>d.id===selected)?.source_file}}
        <span>{{lab.datasets.find(d=>d.id===selected)?.note}}</span>
        <span v-if="lab.datasets.find(d=>d.id===selected)?.revision_of_id" class="version-tag">修订版 · 源自 v{{lab.datasets.find(d=>d.id===selected)?.version!-1}} 原始读数仍可追溯</span>
      </p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>独立试片编号</th><th>参考 X / %</th><th>候选 Y / %</th><th>差值 / 百分点</th></tr></thead>
          <tbody>
            <tr v-for="r in reading.rows" :key="r.id">
              <td><b>{{r.sample_code}}</b></td>
              <td>{{number(r.reference_value,4)}}</td>
              <td>{{number(r.candidate_value,4)}}</td>
              <td class="plum">{{number(r.candidate_value-r.reference_value,4)}}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <EmptyState v-if="!reading.rows.length" title="没有匹配的试片" text="清空试片编号筛选，或导入有完整表头的配对CSV。"/>
      <div class="pagination">
        <span>共{{reading.total}}对 / {{offset+1}}—{{Math.min(offset+20,reading.total)}}</span>
        <div>
          <button :disabled="offset===0" @click="offset-=20;perform(loadRows)">← 前20对</button>
          <button :disabled="offset+20>=reading.total" @click="offset+=20;perform(loadRows)">后20对 →</button>
        </div>
      </div>
    </section>
  </div>
</template>
