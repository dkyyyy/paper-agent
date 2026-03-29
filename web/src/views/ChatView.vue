<script setup lang="ts">
</script>

<template>
  <div class="chat-view">
    <div class="sidebar">
      <!-- Sidebar placeholder -->
      <div class="sidebar-header">
        <h2>Paper Agent</h2>
      </div>
    </div>
    <div class="main">
      <div class="messages">
        <!-- Messages placeholder -->
        <p style="color: #909399; text-align: center; margin-top: 40vh;">
          开始你的学术研究之旅
        </p>
      </div>
      <div class="input-bar">
        <!-- Input placeholder -->
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.chat-view {
  display: flex;
  height: 100vh;
}

.sidebar {
  width: 280px;
  border-right: 1px solid #e4e7ed;
  background: #fff;

  .sidebar-header {
    padding: 16px;
    border-bottom: 1px solid #e4e7ed;

    h2 {
      font-size: 18px;
      color: #303133;
    }
  }
}

.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #f0f2f5;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.input-bar {
  padding: 16px 20px;
  background: #fff;
  border-top: 1px solid #e4e7ed;
}
</style>
