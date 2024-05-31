require "table_show"
JSON = (loadfile "JSON.lua")()
local http = require("socket.http")

function readAll(file)
    local f = assert(io.open(file, "rb"))
    local content = f:read("*all")
    f:close()
    return content
end

QUEUED_URLS = false

function startswith(text, prefix)
    return text:find(prefix, 1, true) == 1
end

wget.callbacks.httploop_result = function(url, err, http_stat)
	--os.execute("sleep 1"i)
	io.stderr:write(http_stat["statcode"] .. " " .. url["url"] .. "\n")
	if http_stat["statcode"] == 401 then
		io.stderr:write(" *** Authorization expired. Sleeping 72000 seconds. Replace authorization file contents.\n\n")
		io.stderr:flush()
		os.execute("sleep 72000")
		return wget.actions.ABORT
	end
	if http_stat["statcode"] ~= 200 then
		if http_stat["statcode"] ~= 404 then
			return wget.actions.ABORT
		end
	end
end

wget.callbacks.get_urls = function(file, url, is_css, iri)
	local addedUrls = {}
	local data = readAll(file)
	print("Read data\n")
	local pat = "https://n1nzo2oxji%.execute%-api%.us%-east%-1%.amazonaws%.com/prod/private/posts/[^/]+/comments%?limit=10.*"
	local mpat = "https://n1nzo2oxji%.execute%-api%.us%-east%-1%.amazonaws%.com/prod/private/posts/([^/]+)/comments%?limit=10.*"
	if url:match(pat) then
		local post_id = string.match(url, mpat)
		local count = 0
		io.stderr:write("This is a comment endpoint\n")
		local decoded = JSON:decode(data)
		if decoded["type"] == "NOT_FOUND" then
			print("Looks like a 404. Marking as complete.")
			return addedUrls
		end
		local discoveredPosts = {}
		for _, comment in ipairs(decoded['items']) do
			print(table.show(comment['postId'], "Discovered comment"))
			table.insert(discoveredPosts, comment['postId'])
			count = count + 1
		end
		if count ~= decoded['count'] then
			print("Aborting item - comment count does NOT MATCH actual count.\n")
			print(table.show(decoded, "Decoded"))
			print(table.show(count, "Count"))
			print("\n")
			os.exit(100)
		end
		local key = decoded["lastEvaluatedKey"]
		if key then
			table.insert(addedUrls, {url = "https://n1nzo2oxji.execute-api.us-east-1.amazonaws.com/prod/private/posts/"..post_id.."/comments?limit=10&exclusiveStartKey="..key})
		end
		local container = {items = discoveredPosts}
		local new_items = JSON:encode(container)
		print("New items", new_items)
		print("Submitting to backfeed")
		local body, code, headers, status = http.request("http://host.docker.internal:5000/", new_items)
		print(body)
		if code ~= 200 then
			print("*** Failed to submit URLs to backfeed!")
			os.exit(105)
		end
		print("Submitted URLs to backfeed.")
	else
		print("Unknown url format")
		os.exit(106)
	end
	io.stderr:write(table.show(addedUrls, "Added URLs"))
	return addedUrls
end
