import smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

server_url = "lithekod.lysator.liu.se"
sender_email = "dev@mail.com"
password = "dev"


def try_construct_link(liu_id, action, links):
    """
    Try to create a link to action for the member with liu_id.
    If a link does not exist a placeholder link is returned instead.

    :param liu_id str: Member to construct link for.
    :param action str: Action of link to construct.
    :param links dict: Links to actions for users.
    """
    if liu_id in links and action in links[liu_id]:
        return "{}/{}".format(server_url, links[liu_id][action])
    return "{}/404".format(server_url)


def send_mail(receivers, subject, html, links={}):
    """
    Send emails to receivers.

    :param receivers list: List of members to receive emails.
    :param subject str: Subject of emails.
    :param html str: HTML template to be rendered.
    :param links dict: Links to actions for users.
    """
    plain = html2text(html)
    for liu_id, name, receiver_email, joined, renewed, receive_info in receivers:
        delete_link = try_construct_link(liu_id, "DELETE", links)
        renew_link = try_construct_link(liu_id, "RENEW", links)
        show_link = try_construct_link(liu_id, "SHOW", links)
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = sender_email
        message["To"] = receiver_email

        plain = plain.format(liu_id=liu_id, name=name, email=receiver_email,
                joined=joined, renewed=renewed, receive_info=receive_info,
                delete_link=delete_link, renew_link=renew_link,
                show_link=show_link)
        html = html.format(liu_id=liu_id, name=name, email=receiver_email,
                joined=joined, renewed=renewed, receive_info=receive_info,
                delete_link=delete_link, renew_link=renew_link,
                show_link=show_link)

        part1 = MIMEText(plain, "plain")
        part2 = MIMEText(html, "html")
        message.attach(part2)

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(sender_email, password)
            server.sendmail(
                sender_email, receiver_email, message.as_string()
            )
