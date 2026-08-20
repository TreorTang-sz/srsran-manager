import { createApp } from 'vue'
import App from './App.vue'
import { startStore } from './store'

const app = createApp(App)
app.mount('#app')
startStore()
