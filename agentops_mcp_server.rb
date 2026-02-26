class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/46/0e/d698e0db253f8a7ff1d5ea5644b9501c06810d488e94508398f7556ea8f8/agentops_mcp_server-0.0.8.tar.gz"
  sha256 "e145040ab48042b0bf304f041dfbdffa4362df040e4d4554fd85ed6f8a9ee751"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
