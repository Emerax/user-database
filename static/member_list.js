import { sendRequest, getGlobal } from "./utils.js";

sendRequest("/members/", new URLSearchParams())
    .then(res => res.json())
    .then(json => {
        let container = document.getElementById("member-id-list");
        json.forEach(member => {
            let elem = document.createElement("div");
            let classAttribute = document.createAttribute("class");
            classAttribute.value = "member-id-list-entry";
            elem.attributes.setNamedItem(classAttribute);
            elem.innerHTML = "<a href=\"/gui/manage_members/" + member.id +
                "\">" + member.id + "</a>";
            container.appendChild(elem);
        });
    });
