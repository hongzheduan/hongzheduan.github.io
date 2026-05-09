import { auth } from "./firebase.js";
import { onAuthStateChanged } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";

export function protectPage(onAllowed) {

onAuthStateChanged(auth, async (user) => {

    if (!user) {
        window.location.href = "login.html";
        return;
    }

    try {

        const res = await fetch(
            `https://us-central1-baizora.cloudfunctions.net/api/get-user?uid=${user.uid}`
        );

        const data = await res.json();

        console.log("UID:", user.uid);
        console.log("API DATA:", data);

        // SAFETY CHECK
        if (!data) {
            window.location.href = "pricing.html";
            return;
        }

        // ADMIN CHECK (email override OR role)
        const isAdmin =
            (user.email && user.email.toLowerCase() === "hongzheduan@gmail.com") ||
            data.role === "admin";

        if (isAdmin) {
            console.log("ADMIN BYPASS ACTIVATED");
            onAllowed(user);
            return;
        }

        // SUBSCRIPTION CHECK
        if (data.subscriptionStatus === "active") {
            onAllowed(user);
        } else {
            window.location.href = "pricing.html";
        }

    } catch (e) {
        console.error("AUTH GUARD ERROR:", e);
        window.location.href = "pricing.html";
    }

});

}