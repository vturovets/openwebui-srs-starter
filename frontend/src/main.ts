import App from './App.svelte';

const target = document.getElementById('app');

if (!target) {
  throw new Error('App root element not found');
}

export default new App({
  target,
});

