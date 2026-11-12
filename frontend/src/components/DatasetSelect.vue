<script setup lang="ts">
import type {Dataset} from '../types/domain';
defineProps<{modelValue:number;datasets:Dataset[]}>();
defineEmits(['update:modelValue']);
</script>
<template>
  <label>配对样本集
    <select :value="modelValue" @change="$emit('update:modelValue',Number(($event.target as HTMLSelectElement).value))">
      <option v-for="d in datasets" :key="d.id" :value="d.id">{{d.name}} / v{{d.version}} / {{d.row_count}} 对{{d.has_successor?' · 已有后继修订版':''}}</option>
    </select>
  </label>
</template>
