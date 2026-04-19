async def handle_admin_reply(event):
    """Handles admin replies in the ticket channel, ensuring token and non-token text are separated."""
    global auto_response_count, last_manual_response_time
    response_text = event.raw_text.strip().lower()
    replied_message = await event.get_reply_message()

    # Skip if no replied message or if it's a separator
    if not replied_message or (replied_message.text and replied_message.text.strip()[0] in ['🟢', '🟣', '🔴']):
        print(f"DEBUG: Skipping admin reply. {'No replied message' if not replied_message else 'Replied to separator'}")
        return

    # Check for links in the response text (exclude emails)
    if has_link(response_text) and not event.message.sticker and not event.message.photo and response_text not in SPECIAL_COMMANDS["confirm"]:
        notify_message = await safe_send_message(client, event.chat_id, "❌ **خطا:** پاسخ حاوی لینک است. لطفاً لینک‌ها را حذف کنید.")
        print(f"❌ DEBUG: Admin reply contains a link: {response_text}")
        await asyncio.sleep(3)
        await notify_message.delete()
        return

    # Initialize variables
    ticket_id = None
    screenshot_id = None
    original_chat_id = None
    moftbar_username = None
    user_message_id = None
    ticket_message_id = None
    ai_response = None
    is_token = False
    is_card = False
    original_message_id = None
    is_screenshot_reply = False
    is_ticket_reply = False
    non_token_text = None

    # Check for matching ticket
    for tid, data in user_tickets.items():
        if data.get("message_id") == replied_message.id:
            ticket_id = tid
            original_chat_id = data["chat_id"]
            moftbar_username = data.get("moftbar_username", "UnknownUser")
            user_message_id = data["user_message_id"]
            ticket_message_id = data["ticket_message_id"]
            ai_response = data.get("ai_response")
            is_token = is_valid_token(user_tickets[ticket_id]["ticket_text"])
            is_card = bool(is_valid_cardnumber(data.get("ticket_text", ""))) if not is_token else False
            is_trx_wallet = bool(is_valid_trx_wallet(data.get("ticket_text", ""))) if not is_token and not is_card else False
            original_message_id = user_message_id
            is_ticket_reply = True
            # Dynamically extract non_token_text based on the current ticket_text
            non_token_text = extract_text_without_token(data["ticket_text"])
            break

    # Check for matching screenshot
    if not ticket_id:
        for sid, data in pending_screenshots.items():
            if data["message_id"] == replied_message.id:
                screenshot_id = sid
                original_chat_id = data["chat_id"]
                moftbar_username = data.get("moftbar_username", "UnknownUser")
                ticket_message_id = data["message_id"]
                original_message_id = data["original_message_id"]
                is_screenshot_reply = True
                break

    if not (is_ticket_reply or is_screenshot_reply):
        print("DEBUG: No matching ticket or screenshot found for reply.")
        return

    # Handle special commands
    if response_text in SPECIAL_COMMANDS["cancel"]:
        template_key = "canceled" if is_ticket_reply else "canceled_screenshot"
        status = "canceled"
        if is_token:
            template_key = "canceled_token"

        if is_ticket_reply:
            user_tickets[ticket_id]["ticket_status"] = status
            await cancel_timer(user_tickets, ticket_id, "Ticket")
        elif is_screenshot_reply:
            await cancel_timer(pending_screenshots, screenshot_id, "Screenshot")
            del pending_screenshots[screenshot_id]
        update_text = await generate_update_text(
            template_key,
            ticket_id=ticket_id,
            token_number=is_token,
            non_token_text=non_token_text,
            screenshot_id=screenshot_id,
            moftbar_username=moftbar_username,
            telegram_username=user_tickets[ticket_id].get("telegram_username", "") if is_ticket_reply else "",
            ticket_text=user_tickets[ticket_id]["ticket_text"] if is_ticket_reply else ""
        )
        await client.edit_message(ticket_channel_chat_ID, ticket_message_id, update_text)
        print(f"⛔ DEBUG: Admin canceled {'Ticket' if is_ticket_reply else 'Screenshot'} {ticket_id or screenshot_id}")
        await manage_separator("canceled")
        return

    if response_text in SPECIAL_COMMANDS["block"]:
        if is_ticket_reply:
            await block_user(original_chat_id)
            update_text = await generate_update_text(
                "blocked",
                ticket_id=ticket_id,
                moftbar_username=moftbar_username,
                telegram_username=user_tickets[ticket_id].get("telegram_username", ""),
                ticket_text=user_tickets[ticket_id]["ticket_text"]
            )
            await client.edit_message(ticket_channel_chat_ID, ticket_message_id, update_text)
            await reset_tickets(original_chat_id)
            notify_message = await safe_send_message(client, event.chat_id, f"❌**کاربر بلاک شد.**❌")
            await asyncio.sleep(3)
            await notify_message.delete()
            await manage_separator("resolved")
        return

    if response_text in SPECIAL_COMMANDS["reset"]:
        await reset_tickets(original_chat_id)
        notify_message = await safe_send_message(client, event.chat_id, f"❌**کلیه پیامهای باز `{moftbar_username}` نادیده گرفته شد**❌")
        await asyncio.sleep(3)
        await notify_message.delete()
        await manage_separator("resolved")
        return

    # Handle response types
    is_sticker = event.message.sticker is not None
    is_photo = event.message.photo is not None
    final_message = response_text
    is_ai_response = False

    if response_text in SPECIAL_COMMANDS["confirm"]:
        final_message = ai_response or "🤖 AI پاسخ خودکار موجود نیست."
        is_ai_response = True
        last_manual_response_time = time.time()
        auto_response_count = 0
        await event.message.delete()

    # Determine template key
    template_key = "screenshot" if is_screenshot_reply else "ticket_token" if is_token else "ticket_card" if is_card else "ticket_text"

    # Generate update text
    if is_sticker:
        sticker_id = event.message.file.id
        await client.send_file(original_chat_id, sticker_id, reply_to=original_message_id)
        if is_ticket_reply:
            add_qa_with_sticker(user_tickets[ticket_id]["ticket_text"], None, sticker_id)
        update_text = await generate_update_text(
            template_key,
            ticket_id=ticket_id,
            screenshot_id=screenshot_id if is_screenshot_reply else None,
            moftbar_username=moftbar_username,
            telegram_username=user_tickets[ticket_id].get("telegram_username", "") if is_ticket_reply else "",
            ticket_text=user_tickets[ticket_id]["ticket_text"] if is_ticket_reply else "",
            response_text="Sticker sent.",
            status_text=STATUS_TEXTS["resolved_sticker"]
        )
        notify_message = await safe_send_message(client, event.chat_id, "✅ Sticker sent to user!")
    elif is_photo:
        file_path = await event.message.download_media()
        await client.send_file(original_chat_id, file_path, reply_to=original_message_id)
        if is_ticket_reply:
            add_qa_with_image(user_tickets[ticket_id]["ticket_text"], image_path=file_path)
        update_text = await generate_update_text(
            template_key,
            ticket_id=ticket_id,
            screenshot_id=screenshot_id if is_screenshot_reply else None,
            moftbar_username=moftbar_username,
            telegram_username=user_tickets[ticket_id].get("telegram_username", "") if is_ticket_reply else "",
            ticket_text=user_tickets[ticket_id]["ticket_text"] if is_ticket_reply else "",
            response_text="Photo sent.",
            status_text=STATUS_TEXTS["resolved_photo"]
        )
        notify_message = await safe_send_message(client, event.chat_id, "✅ Photo sent to user!")
    else:
        if is_ticket_reply:
            add_qa(user_tickets[ticket_id]["ticket_text"], final_message)
        update_text = await generate_update_text(
            template_key,
            ticket_id=ticket_id,
            screenshot_id=screenshot_id if is_screenshot_reply else None,
            moftbar_username=moftbar_username,
            telegram_username=user_tickets[ticket_id].get("telegram_username", "") if is_ticket_reply else "",
            ticket_text=user_tickets[ticket_id]["ticket_text"] if is_ticket_reply else "",
            response_text=final_message,
            status_text=STATUS_TEXTS["resolved_ai" if is_ai_response else "resolved_text"]
        )
        if is_ai_response and user_tickets[ticket_id].get("ai_response_message_id"):
            try:
                await client.edit_message(original_chat_id, user_tickets[ticket_id]["ai_response_message_id"], final_message)
                auto_response_count = max(0, auto_response_count - 1)
            except Exception as e:
                print(f"❌ ERROR: Failed to edit AI response - {e}")
                await safe_send_message(client, original_chat_id, final_message, reply_to=original_message_id)
        else:
            await safe_send_message(client, original_chat_id, final_message, reply_to=original_message_id)
        await append_to_conversation_history(original_chat_id, "bot", final_message)
        notify_message = await safe_send_message(client, event.chat_id, 
            f"✅ پاسخ به {'تیکت' if is_ticket_reply else 'اسکرین‌شات'} `{ticket_id or screenshot_id}` ارسال شد.")

    # Update ticket or screenshot status
    if is_ticket_reply:
        await cancel_timer(user_tickets, ticket_id, "Ticket")
        if user_tickets[ticket_id].get("pinned_warning_id"):
            try:
                await client.unpin_message(original_chat_id, user_tickets[ticket_id]["pinned_warning_id"])
                await client.delete_messages(original_chat_id, user_tickets[ticket_id]["pinned_warning_id"])
                del user_tickets[ticket_id]["pinned_warning_id"]
            except Exception as e:
                print(f"ERROR: Konnte gepinnte Warnnachricht nicht löschen - {e}")
        user_tickets[ticket_id]["ticket_status"] = "resolved" if response_text not in SPECIAL_COMMANDS["cancel"] else "canceled"
        user_tickets[ticket_id]["admin_response"] = final_message
    else:
        await cancel_timer(pending_screenshots, screenshot_id, "Screenshot")
        del pending_screenshots[screenshot_id]

    # Edit ticket/screenshot message
    try:
        current_message = await client.get_messages(ticket_channel_chat_ID, ids=ticket_message_id)
        # Handle both single message and list cases
        if isinstance(current_message, list) and len(current_message) > 0:
            current_message = current_message[0]
        current_text = current_message.text if current_message and hasattr(current_message, 'text') else ""
        if update_text != current_text:
            await client.edit_message(ticket_channel_chat_ID, ticket_message_id, update_text)
        else:
            update_text += f"\n🕒 Edited: {datetime.datetime.now().strftime('%H:%M:%S')}"
            await client.edit_message(ticket_channel_chat_ID, ticket_message_id, update_text)
            print(f"⚠️ DEBUG: Forced edit with timestamp for {'Ticket' if is_ticket_reply else 'Screenshot'} {ticket_id or screenshot_id}")
    except MessageNotModifiedError:
        print(f"⚠️ DEBUG: Message not modified for {'Ticket' if is_ticket_reply else 'Screenshot'} {ticket_id or screenshot_id}")
    except Exception as e:
        print(f"❌ ERROR: Failed to edit message - {e}")

    # Clean up notify message
    if 'notify_message' in locals():
        await asyncio.sleep(3)
        await notify_message.delete()

    await manage_separator("resolved" if response_text not in SPECIAL_COMMANDS["cancel"] else "canceled") 