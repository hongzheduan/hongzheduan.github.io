import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import { getAuth } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";
import { getFirestore } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore.js";

const firebaseConfig = {
  apiKey: "AIzaSyDVX4hPWgY_JK3VyXDjZapeki6Mm-tvw80",
  authDomain: "baizora.firebaseapp.com",
  projectId: "baizora",
  appId: "1:1046306710691:web:b871cdedee87e9e6574b16"
};

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
export const db = getFirestore(app);