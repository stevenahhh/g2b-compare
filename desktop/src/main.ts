import { mount } from "svelte";

import App from "./App.svelte";
import "./app.css";

const target = document.getElementById("app");

if (target === null) {
  throw new Error("앱 마운트 지점을 찾을 수 없습니다.");
}

mount(App, { target });
